from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.account_data import (
    AccountDeletionError,
    delete_account_data,
    export_account_data,
)
from backend.auth import resolve_or_provision_account
from backend.billing import (
    InvalidWebhookError,
    SubscriptionSnapshot,
    snapshot_from_stripe,
)
from backend.config import Settings
from backend.db import DatabaseRuntime
from backend.main import create_app
from backend.models import (
    Account,
    Base,
    BillingCustomer,
    BillingSubscription,
    Group,
    GroupMembership,
    MembershipRole,
    User,
)
from backend.terms import CURRENT_TERMS_VERSION
from backend.tests.test_phase_2b_auth import MockRequestAuthenticator

BILLING_ENV = {
    "BILLING_ENABLED": True,
    "APP_PUBLIC_URL": "https://planner.example",
    "STRIPE_SECRET_KEY": "sk_test_synthetic",
    "STRIPE_WEBHOOK_SECRET": "whsec_synthetic",
    "STRIPE_PRICE_PRO_MONTHLY": "price_monthly",
    "STRIPE_PRICE_PRO_YEARLY": "price_yearly",
}
PERIOD_END = datetime(2026, 11, 17, tzinfo=timezone.utc)


def _settings(**overrides: Any) -> Settings:
    return Settings(
        _env_file=None,
        APP_ENV="test",
        LOG_LEVEL="CRITICAL",
        CORS_ALLOWED_ORIGINS=["http://testserver"],
        **{**BILLING_ENV, **overrides},
    )


class FakeGateway:
    def __init__(self) -> None:
        self.customers: list[tuple[str | None, uuid.UUID]] = []
        self.checkouts: list[dict[str, Any]] = []
        self.portals: list[dict[str, Any]] = []
        self.subscriptions: dict[str, SubscriptionSnapshot] = {}
        self.events: dict[bytes, dict[str, Any]] = {}

    def create_customer(self, *, email: str | None, user_id: uuid.UUID) -> str:
        self.customers.append((email, user_id))
        return f"cus_{len(self.customers)}"

    def create_checkout_session(self, **kwargs: Any) -> str:
        self.checkouts.append(kwargs)
        return "https://checkout.stripe.test/session"

    def create_portal_session(self, **kwargs: Any) -> str:
        self.portals.append(kwargs)
        return "https://billing.stripe.test/portal"

    def retrieve_subscription(self, subscription_id: str) -> SubscriptionSnapshot:
        return self.subscriptions[subscription_id]

    def construct_event(self, payload: bytes, signature: str) -> dict[str, Any]:
        if signature != "valid":
            raise InvalidWebhookError("bad signature")
        return self.events[payload]


def _snapshot(status: str = "active", **changes: Any) -> SubscriptionSnapshot:
    return replace(
        SubscriptionSnapshot(
            stripe_subscription_id="sub_1",
            stripe_customer_id="cus_1",
            status=status,
            stripe_price_id="price_monthly",
            billing_interval="month",
            current_period_end=PERIOD_END,
            cancel_at_period_end=False,
            metadata_user_id=None,
        ),
        **changes,
    )


@pytest.fixture
def runtime(tmp_path: Path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'billing.db'}")

    @sa.event.listens_for(engine, "connect")
    def configure(connection, _):
        connection.create_function(
            "btrim", 1, lambda value: value.strip() if value else value
        )
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    runtime = DatabaseRuntime(engine=engine, safe_url="synthetic local test database")
    yield runtime
    runtime.dispose()


@pytest.fixture
def gm(runtime: DatabaseRuntime) -> uuid.UUID:
    with Session(runtime.engine) as session:
        account = resolve_or_provision_account(session, "clerk", "billing-gm")
        account.email = "gm@example.test"
        account.terms_version = CURRENT_TERMS_VERSION
        account.terms_accepted_at = datetime.now(timezone.utc)
        user = User(account_id=account.id, display_name="GM")
        session.add(user)
        session.commit()
        return user.id


def _own_groups(runtime: DatabaseRuntime, user_id: uuid.UUID, count: int) -> None:
    with Session(runtime.engine) as session:
        for index in range(count):
            group = Group(name=f"Table {index}")
            session.add(group)
            session.flush()
            session.add(
                GroupMembership(
                    group_id=group.id,
                    user_id=user_id,
                    role=MembershipRole.OWNER,
                    display_order=0,
                )
            )
        session.commit()


def _client(runtime: DatabaseRuntime, app_settings: Settings, gateway: FakeGateway):
    auth = MockRequestAuthenticator()
    auth.add_session(token="gm", subject="billing-gm", email="gm@example.test")
    app = create_app(app_settings, database_runtime=runtime)
    patcher = patch("backend.main.validate_database_readiness")
    patcher.start()
    client = TestClient(app)
    client.__enter__()
    app.state.request_authenticator = auth
    app.state.clerk_profile_client = auth
    app.state.billing_gateway = gateway
    client.headers["Authorization"] = "Bearer gm"
    return client, patcher


@pytest.fixture
def gateway() -> FakeGateway:
    return FakeGateway()


@pytest.fixture
def client(runtime: DatabaseRuntime, gm: uuid.UUID, gateway: FakeGateway):
    client, patcher = _client(runtime, _settings(), gateway)
    yield client
    client.__exit__(None, None, None)
    patcher.stop()


def _create_group(client: TestClient, name: str = "New table"):
    return client.post("/api/groups", json={"name": name, "timezone": "UTC"})


def _subscribe(runtime: DatabaseRuntime, user_id: uuid.UUID, status: str) -> None:
    with Session(runtime.engine) as session:
        session.add(BillingCustomer(user_id=user_id, stripe_customer_id="cus_1"))
        session.add(
            BillingSubscription(
                user_id=user_id,
                stripe_subscription_id="sub_1",
                status=status,
                billing_interval="month",
                current_period_end=PERIOD_END,
            )
        )
        session.commit()


def test_billing_settings_require_complete_stripe_configuration() -> None:
    assert _settings().app_public_url == "https://planner.example"
    with pytest.raises(ValidationError, match="STRIPE_WEBHOOK_SECRET"):
        _settings(STRIPE_WEBHOOK_SECRET="")
    with pytest.raises(ValidationError, match="Stripe price ID"):
        _settings(STRIPE_PRICE_PRO_YEARLY="prod_123")
    with pytest.raises(ValidationError, match="APP_PUBLIC_URL"):
        _settings(APP_PUBLIC_URL="https://planner.example/account")
    disabled = Settings(_env_file=None, APP_ENV="test")
    assert disabled.billing_enabled is False


def test_disabled_billing_keeps_unlimited_groups_and_hides_endpoints(
    runtime: DatabaseRuntime, gm: uuid.UUID, gateway: FakeGateway
) -> None:
    _own_groups(runtime, gm, 3)
    client, patcher = _client(
        runtime, Settings(_env_file=None, APP_ENV="test"), gateway
    )
    try:
        assert _create_group(client).status_code == 201
        membership = client.get("/api/me/membership").json()
        assert membership["billing_enabled"] is False
        assert membership["owned_group_limit"] is None
        assert (
            client.post("/api/billing/checkout", json={"interval": "month"}).status_code
            == 404
        )
        assert (
            client.post(
                "/api/billing/webhook",
                content=b"{}",
                headers={"stripe-signature": "valid"},
            ).status_code
            == 404
        )
    finally:
        client.__exit__(None, None, None)
        patcher.stop()


def test_free_plan_limits_owned_groups_but_not_joined_ones(
    client: TestClient, runtime: DatabaseRuntime, gm: uuid.UUID
) -> None:
    assert _create_group(client, "First").status_code == 201
    assert _create_group(client, "Second").status_code == 201
    blocked = _create_group(client, "Third")
    assert blocked.status_code == 403
    assert "up to 2 groups" in blocked.json()["detail"]
    membership = client.get("/api/me/membership").json()
    assert membership == {
        "billing_enabled": True,
        "plan": "free",
        "owned_groups": 2,
        "owned_group_limit": 2,
        "subscription": None,
        "can_manage_billing": False,
    }


def test_existing_owners_above_the_limit_keep_their_groups(
    client: TestClient, runtime: DatabaseRuntime, gm: uuid.UUID
) -> None:
    _own_groups(runtime, gm, 4)
    assert _create_group(client).status_code == 403
    assert len(client.get("/api/me/groups").json()) == 4


@pytest.mark.parametrize("status", ["active", "trialing", "past_due"])
def test_pro_subscription_removes_the_group_limit(
    client: TestClient, runtime: DatabaseRuntime, gm: uuid.UUID, status: str
) -> None:
    _own_groups(runtime, gm, 2)
    _subscribe(runtime, gm, status)
    assert _create_group(client).status_code == 201
    membership = client.get("/api/me/membership").json()
    assert membership["plan"] == "pro"
    assert membership["owned_group_limit"] is None
    assert membership["subscription"]["billing_interval"] == "month"
    assert membership["can_manage_billing"] is True


@pytest.mark.parametrize("status", ["canceled", "unpaid", "incomplete", "paused"])
def test_ended_or_unpaid_subscription_is_free(
    client: TestClient, runtime: DatabaseRuntime, gm: uuid.UUID, status: str
) -> None:
    _own_groups(runtime, gm, 2)
    _subscribe(runtime, gm, status)
    assert _create_group(client).status_code == 403
    assert client.get("/api/me/membership").json()["plan"] == "free"


def test_checkout_creates_one_customer_and_uses_the_chosen_price(
    client: TestClient, gateway: FakeGateway, runtime: DatabaseRuntime, gm: uuid.UUID
) -> None:
    first = client.post("/api/billing/checkout", json={"interval": "year"})
    second = client.post("/api/billing/checkout", json={"interval": "month"})
    assert first.status_code == second.status_code == 200
    assert first.json() == {"url": "https://checkout.stripe.test/session"}
    assert gateway.customers == [("gm@example.test", gm)]
    assert [c["price_id"] for c in gateway.checkouts] == [
        "price_yearly",
        "price_monthly",
    ]
    assert {c["customer_id"] for c in gateway.checkouts} == {"cus_1"}
    assert gateway.checkouts[0]["success_url"] == (
        "https://planner.example/account?membership=success"
    )
    assert (
        client.post("/api/billing/checkout", json={"interval": "week"}).status_code
        == 422
    )


def test_checkout_refuses_existing_pro_and_portal_needs_a_customer(
    client: TestClient, gateway: FakeGateway, runtime: DatabaseRuntime, gm: uuid.UUID
) -> None:
    assert client.post("/api/billing/portal").status_code == 404
    _subscribe(runtime, gm, "active")
    assert (
        client.post("/api/billing/checkout", json={"interval": "month"}).status_code
        == 409
    )
    portal = client.post("/api/billing/portal")
    assert portal.json() == {"url": "https://billing.stripe.test/portal"}
    assert gateway.portals == [
        {"customer_id": "cus_1", "return_url": "https://planner.example/account"}
    ]


def test_webhook_rejects_missing_or_invalid_signatures(client: TestClient) -> None:
    assert client.post("/api/billing/webhook", content=b"{}").status_code == 400
    assert (
        client.post(
            "/api/billing/webhook",
            content=b"{}",
            headers={"stripe-signature": "forged"},
        ).status_code
        == 400
    )


def _deliver(client: TestClient, gateway: FakeGateway, event: dict[str, Any]):
    payload = repr(event).encode()
    gateway.events[payload] = event
    return client.post(
        "/api/billing/webhook", content=payload, headers={"stripe-signature": "valid"}
    )


def test_webhooks_sync_current_state_even_when_repeated_or_out_of_order(
    client: TestClient, gateway: FakeGateway, runtime: DatabaseRuntime, gm: uuid.UUID
) -> None:
    assert (
        client.post("/api/billing/checkout", json={"interval": "month"}).status_code
        == 200
    )
    gateway.subscriptions["sub_1"] = _snapshot("active")
    completed = {
        "type": "checkout.session.completed",
        "data": {"object": {"subscription": "sub_1"}},
    }
    assert _deliver(client, gateway, completed).status_code == 200
    assert _deliver(client, gateway, completed).status_code == 200
    assert client.get("/api/me/membership").json()["plan"] == "pro"

    # Stripe now says the subscription is cancelled; an older "updated" event
    # delivered late still converges on that current state.
    gateway.subscriptions["sub_1"] = _snapshot("canceled")
    stale = {
        "type": "customer.subscription.updated",
        "data": {"object": {"id": "sub_1", "status": "active"}},
    }
    assert _deliver(client, gateway, stale).status_code == 200
    assert client.get("/api/me/membership").json()["plan"] == "free"
    with Session(runtime.engine) as session:
        assert (
            session.scalar(sa.select(sa.func.count()).select_from(BillingSubscription))
            == 1
        )


def test_webhook_ignores_unknown_customers_and_unrelated_events(
    client: TestClient, gateway: FakeGateway, runtime: DatabaseRuntime
) -> None:
    gateway.subscriptions["sub_x"] = _snapshot(
        stripe_subscription_id="sub_x", stripe_customer_id="cus_other"
    )
    event = {
        "type": "customer.subscription.created",
        "data": {"object": {"id": "sub_x"}},
    }
    assert _deliver(client, gateway, event).status_code == 200
    assert (
        _deliver(
            client,
            gateway,
            {"type": "invoice.paid", "data": {"object": {"id": "in_1"}}},
        ).status_code
        == 200
    )
    with Session(runtime.engine) as session:
        assert (
            session.scalar(sa.select(sa.func.count()).select_from(BillingSubscription))
            == 0
        )


def test_webhook_failure_returns_500_so_stripe_retries(
    client: TestClient, gateway: FakeGateway
) -> None:
    event = {
        "type": "customer.subscription.updated",
        "data": {"object": {"id": "sub_missing"}},
    }
    assert _deliver(client, gateway, event).status_code == 500


def test_snapshot_reads_item_period_and_price_interval() -> None:
    snapshot = snapshot_from_stripe(
        {
            "id": "sub_1",
            "customer": "cus_1",
            "status": "active",
            "cancel_at_period_end": True,
            "metadata": {"dnd_user_id": "abc"},
            "items": {
                "data": [
                    {
                        "current_period_end": int(PERIOD_END.timestamp()),
                        "price": {
                            "id": "price_yearly",
                            "recurring": {"interval": "year"},
                        },
                    }
                ]
            },
        }
    )
    assert snapshot == SubscriptionSnapshot(
        stripe_subscription_id="sub_1",
        stripe_customer_id="cus_1",
        status="active",
        stripe_price_id="price_yearly",
        billing_interval="year",
        current_period_end=PERIOD_END,
        cancel_at_period_end=True,
        metadata_user_id="abc",
    )


def test_export_includes_billing_and_deletion_waits_for_cancellation(
    runtime: DatabaseRuntime, gm: uuid.UUID
) -> None:
    _subscribe(runtime, gm, "active")
    with Session(runtime.engine) as session:
        account = session.scalar(
            sa.select(Account).join(User, User.account_id == Account.id)
        )
        exported = export_account_data(session, account)
        account_id = account.id
    assert exported["billing_customer"]["stripe_customer_id"] == "cus_1"
    assert exported["billing_subscriptions"][0]["status"] == "active"

    with Session(runtime.engine) as session:
        with pytest.raises(AccountDeletionError, match="Cancel the PRO subscription"):
            delete_account_data(session, account_id, apply=True)
    with Session(runtime.engine) as session:
        session.execute(sa.update(BillingSubscription).values(status="canceled"))
        session.commit()
    with Session(runtime.engine) as session:
        summary = delete_account_data(session, account_id, apply=True)
    assert summary["applied"] is True
    assert summary["billing_subscriptions"] == 1
    with Session(runtime.engine) as session:
        assert (
            session.scalar(sa.select(sa.func.count()).select_from(BillingCustomer)) == 0
        )


def test_stripe_gateway_verifies_real_signatures_and_returns_plain_data() -> None:
    import hashlib
    import hmac
    import json
    import time

    from backend.billing import StripeBillingGateway

    gateway = StripeBillingGateway(_settings())
    payload = json.dumps(
        {
            "id": "evt_1",
            "object": "event",
            "type": "checkout.session.completed",
            "data": {"object": {"object": "checkout.session", "subscription": "sub_1"}},
        }
    ).encode()
    timestamp = int(time.time())
    digest = hmac.new(
        b"whsec_synthetic", f"{timestamp}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    event = gateway.construct_event(payload, f"t={timestamp},v1={digest}")
    assert isinstance(event, dict)
    assert event["data"]["object"]["subscription"] == "sub_1"
    with pytest.raises(InvalidWebhookError):
        gateway.construct_event(payload, f"t={timestamp},v1={'0' * 64}")
    with pytest.raises(InvalidWebhookError):
        gateway.construct_event(b"not json", "t=1,v1=00")
