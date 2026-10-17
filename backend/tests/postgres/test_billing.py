"""Synthetic PostgreSQL membership checks; no real accounts or Stripe calls."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.auth import get_current_dnd_user
from backend.config import Settings
from backend.db import create_database_runtime
from backend.main import create_app
from backend.models import BillingCustomer, BillingSubscription, User


@pytest.fixture
def api(postgres_database_url, db_session):
    user = User(display_name="GM")
    db_session.add(user)
    db_session.commit()
    runtime = create_database_runtime(postgres_database_url)
    app = create_app(
        Settings(
            _env_file=None,
            APP_ENV="test",
            LOG_LEVEL="CRITICAL",
            DATABASE_URL=postgres_database_url,
            MUTATIONS_ENABLED=True,
            BILLING_ENABLED=True,
            FREE_OWNED_GROUP_LIMIT=1,
            APP_PUBLIC_URL="https://planner.example",
            STRIPE_SECRET_KEY="sk_test_synthetic",
            STRIPE_WEBHOOK_SECRET="whsec_synthetic",
            STRIPE_PRICE_PRO_MONTHLY="price_monthly",
            STRIPE_PRICE_PRO_YEARLY="price_yearly",
        ),
        runtime,
    )
    app.dependency_overrides[get_current_dnd_user] = lambda: user
    with TestClient(app) as client:
        yield client, user


def test_free_limit_and_pro_subscription_on_postgres(api, db_session):
    client, user = api
    assert client.post("/api/groups", json={"name": "One"}).status_code == 201
    blocked = client.post("/api/groups", json={"name": "Two"})
    assert blocked.status_code == 403
    assert "up to 1 group." in blocked.json()["detail"]

    db_session.add(BillingCustomer(user_id=user.id, stripe_customer_id="cus_pg"))
    db_session.add_all(
        [
            BillingSubscription(
                user_id=user.id,
                stripe_subscription_id="sub_old",
                status="canceled",
                current_period_end=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
            BillingSubscription(
                user_id=user.id,
                stripe_subscription_id="sub_new",
                status="active",
                billing_interval="year",
            ),
        ]
    )
    db_session.commit()
    assert client.post("/api/groups", json={"name": "Two"}).status_code == 201
    membership = client.get("/api/me/membership").json()
    assert membership["plan"] == "pro"
    assert membership["owned_groups"] == 2
    assert membership["subscription"]["billing_interval"] == "year"
