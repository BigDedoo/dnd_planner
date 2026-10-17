"""PRO membership: plan rules, Stripe Checkout/Portal and signed webhooks.

Stripe is the source of truth for billing state. Webhooks never trust the
event payload's copy of a subscription: they re-read the subscription from
Stripe and store its current state, so repeated or out-of-order deliveries
converge on the same row.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal, Protocol

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .auth import get_current_account, get_current_dnd_user
from .config import Settings
from .db import get_request_session
from .models import (
    PRO_SUBSCRIPTION_STATUSES,
    Account,
    BillingCustomer,
    BillingSubscription,
    GroupMembership,
    MembershipRole,
    User,
)

logger = logging.getLogger(__name__)
router = APIRouter()

SUBSCRIPTION_EVENTS = frozenset(
    {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "customer.subscription.paused",
        "customer.subscription.resumed",
    }
)


class Plan(StrEnum):
    FREE = "free"
    PRO = "pro"


class BillingNotConfiguredError(RuntimeError):
    pass


class InvalidWebhookError(ValueError):
    pass


@dataclass(frozen=True)
class SubscriptionSnapshot:
    stripe_subscription_id: str
    stripe_customer_id: str
    status: str
    stripe_price_id: str | None
    billing_interval: str | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    metadata_user_id: str | None


class BillingGateway(Protocol):
    def create_customer(self, *, email: str | None, user_id: uuid.UUID) -> str: ...

    def create_checkout_session(
        self,
        *,
        customer_id: str,
        price_id: str,
        user_id: uuid.UUID,
        success_url: str,
        cancel_url: str,
    ) -> str: ...

    def create_portal_session(self, *, customer_id: str, return_url: str) -> str: ...

    def retrieve_subscription(self, subscription_id: str) -> SubscriptionSnapshot: ...

    def construct_event(self, payload: bytes, signature: str) -> dict[str, Any]: ...


def _get(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    try:
        return obj[key]
    except (KeyError, TypeError):
        return None


def _stripe_id(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    return _get(value, "id")


def snapshot_from_stripe(subscription: Any) -> SubscriptionSnapshot:
    items = _get(_get(subscription, "items"), "data") or []
    first_item = items[0] if items else None
    price = _get(first_item, "price")
    interval = _get(_get(price, "recurring"), "interval")
    # Newer Stripe API versions report the period on the item, older ones on
    # the subscription itself.
    period_end = _get(first_item, "current_period_end") or _get(
        subscription, "current_period_end"
    )
    metadata = _get(subscription, "metadata") or {}
    return SubscriptionSnapshot(
        stripe_subscription_id=subscription["id"],
        stripe_customer_id=_stripe_id(_get(subscription, "customer")) or "",
        status=str(_get(subscription, "status") or ""),
        stripe_price_id=_stripe_id(price),
        billing_interval=interval if interval in {"month", "year"} else None,
        current_period_end=(
            datetime.fromtimestamp(int(period_end), tz=timezone.utc)
            if period_end
            else None
        ),
        cancel_at_period_end=bool(_get(subscription, "cancel_at_period_end")),
        metadata_user_id=_get(metadata, "dnd_user_id"),
    )


class StripeBillingGateway:
    def __init__(self, app_settings: Settings) -> None:
        import stripe

        secret = app_settings.stripe_secret_key
        webhook_secret = app_settings.stripe_webhook_secret
        if secret is None or webhook_secret is None:
            raise BillingNotConfiguredError("Stripe is not configured")
        self._client = stripe.StripeClient(secret.get_secret_value())
        self._webhook_secret = webhook_secret.get_secret_value()
        self._automatic_tax = app_settings.stripe_automatic_tax
        self._signature_error = stripe.SignatureVerificationError

    def create_customer(self, *, email: str | None, user_id: uuid.UUID) -> str:
        params: dict[str, Any] = {"metadata": {"dnd_user_id": str(user_id)}}
        if email:
            params["email"] = email
        return self._client.v1.customers.create(params=params).id

    def create_checkout_session(
        self,
        *,
        customer_id: str,
        price_id: str,
        user_id: uuid.UUID,
        success_url: str,
        cancel_url: str,
    ) -> str:
        params: dict[str, Any] = {
            "mode": "subscription",
            "customer": customer_id,
            "client_reference_id": str(user_id),
            "line_items": [{"price": price_id, "quantity": 1}],
            "subscription_data": {"metadata": {"dnd_user_id": str(user_id)}},
            "allow_promotion_codes": True,
            "success_url": success_url,
            "cancel_url": cancel_url,
        }
        if self._automatic_tax:
            # Stripe Tax needs the customer's address to pick the VAT rate.
            params["automatic_tax"] = {"enabled": True}
            params["customer_update"] = {"address": "auto", "name": "auto"}
        checkout = self._client.v1.checkout.sessions.create(params=params)
        return checkout.url

    def create_portal_session(self, *, customer_id: str, return_url: str) -> str:
        portal = self._client.v1.billing_portal.sessions.create(
            params={"customer": customer_id, "return_url": return_url}
        )
        return portal.url

    def retrieve_subscription(self, subscription_id: str) -> SubscriptionSnapshot:
        return snapshot_from_stripe(
            self._client.v1.subscriptions.retrieve(subscription_id).to_dict()
        )

    def construct_event(self, payload: bytes, signature: str) -> dict[str, Any]:
        try:
            event = self._client.construct_event(
                payload, signature, self._webhook_secret
            )
        except (ValueError, self._signature_error) as exc:
            raise InvalidWebhookError("invalid Stripe webhook") from exc
        # Stripe objects are not dicts; hand plain data to the handler.
        return event.to_dict()


def get_billing_gateway(request: Request) -> BillingGateway:
    app_settings: Settings = request.app.state.settings
    if not app_settings.billing_enabled:
        raise HTTPException(status_code=404, detail="Memberships are not available")
    gateway = getattr(request.app.state, "billing_gateway", None)
    if gateway is None:
        gateway = StripeBillingGateway(app_settings)
        request.app.state.billing_gateway = gateway
    return gateway


def owned_group_count(session: Session, user_id: uuid.UUID) -> int:
    return (
        session.scalar(
            sa.select(sa.func.count())
            .select_from(GroupMembership)
            .where(
                GroupMembership.user_id == user_id,
                GroupMembership.role == MembershipRole.OWNER,
            )
        )
        or 0
    )


def active_subscription(
    session: Session, user_id: uuid.UUID
) -> BillingSubscription | None:
    return session.scalar(
        sa.select(BillingSubscription)
        .where(
            BillingSubscription.user_id == user_id,
            BillingSubscription.status.in_(PRO_SUBSCRIPTION_STATUSES),
        )
        .order_by(BillingSubscription.current_period_end.desc().nulls_last())
        .limit(1)
    )


def resolve_plan(session: Session, user_id: uuid.UUID) -> Plan:
    if active_subscription(session, user_id) is not None:
        return Plan.PRO
    return Plan.FREE


def owned_group_limit(
    app_settings: Settings, session: Session, user_id: uuid.UUID
) -> int | None:
    """None means unlimited. The limit only applies once billing is live."""
    if not app_settings.billing_enabled:
        return None
    if resolve_plan(session, user_id) is Plan.PRO:
        return None
    return app_settings.free_owned_group_limit


def require_group_creation_allowed(
    app_settings: Settings, session: Session, user: User
) -> None:
    """Call inside the group-creation transaction, before adding the group."""
    if not app_settings.billing_enabled:
        return
    # Serialize concurrent creations by the same user so both cannot pass the
    # count check before either commits.
    session.scalar(sa.select(User.id).where(User.id == user.id).with_for_update())
    limit = owned_group_limit(app_settings, session, user.id)
    if limit is not None and owned_group_count(session, user.id) >= limit:
        group_word = "group" if limit == 1 else "groups"
        raise HTTPException(
            status_code=403,
            detail=(
                f"Free accounts can own up to {limit} {group_word}. Upgrade to "
                "PRO from your Account page to create more."
            ),
        )


def sync_subscription(session: Session, snapshot: SubscriptionSnapshot) -> bool:
    """Upsert Stripe's current subscription state. Returns False if unmatched."""
    user_id = session.scalar(
        sa.select(BillingCustomer.user_id).where(
            BillingCustomer.stripe_customer_id == snapshot.stripe_customer_id
        )
    )
    if user_id is None:
        logger.warning(
            "billing_subscription_unmatched subscription=%s",
            snapshot.stripe_subscription_id,
        )
        return False
    if snapshot.metadata_user_id not in {None, str(user_id)}:
        logger.warning(
            "billing_subscription_user_mismatch subscription=%s",
            snapshot.stripe_subscription_id,
        )
    row = session.scalar(
        sa.select(BillingSubscription)
        .where(
            BillingSubscription.stripe_subscription_id
            == snapshot.stripe_subscription_id
        )
        .with_for_update()
    )
    if row is None:
        row = BillingSubscription(
            user_id=user_id,
            stripe_subscription_id=snapshot.stripe_subscription_id,
        )
        session.add(row)
    row.status = snapshot.status
    row.stripe_price_id = snapshot.stripe_price_id
    row.billing_interval = snapshot.billing_interval
    row.current_period_end = snapshot.current_period_end
    row.cancel_at_period_end = snapshot.cancel_at_period_end
    return True


def handle_webhook_event(
    session: Session, gateway: BillingGateway, event: dict[str, Any]
) -> None:
    event_type = event["type"]
    data_object = event["data"]["object"]
    if event_type == "checkout.session.completed":
        subscription_id = _stripe_id(_get(data_object, "subscription"))
    elif event_type in SUBSCRIPTION_EVENTS:
        subscription_id = _get(data_object, "id")
    else:
        return
    if not subscription_id:
        return
    snapshot = gateway.retrieve_subscription(subscription_id)
    sync_subscription(session, snapshot)
    session.commit()


class MembershipSubscription(BaseModel):
    status: str
    billing_interval: Literal["month", "year"] | None
    current_period_end: datetime | None
    cancel_at_period_end: bool


class MembershipResponse(BaseModel):
    billing_enabled: bool
    plan: Plan
    owned_groups: int
    owned_group_limit: int | None
    subscription: MembershipSubscription | None
    can_manage_billing: bool


class CheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interval: Literal["month", "year"]


class RedirectResponse(BaseModel):
    url: str


@router.get("/me/membership", response_model=MembershipResponse)
@router.get("/api/me/membership", response_model=MembershipResponse)
def get_my_membership(
    request: Request,
    user: User = Depends(get_current_dnd_user),
    session: Session = Depends(get_request_session),
):
    app_settings: Settings = request.app.state.settings
    subscription = active_subscription(session, user.id)
    has_customer = (
        session.get(BillingCustomer, user.id) is not None
        if app_settings.billing_enabled
        else False
    )
    return MembershipResponse(
        billing_enabled=app_settings.billing_enabled,
        plan=Plan.PRO if subscription is not None else Plan.FREE,
        owned_groups=owned_group_count(session, user.id),
        owned_group_limit=owned_group_limit(app_settings, session, user.id),
        subscription=(
            MembershipSubscription(
                status=subscription.status,
                billing_interval=subscription.billing_interval,
                current_period_end=subscription.current_period_end,
                cancel_at_period_end=subscription.cancel_at_period_end,
            )
            if subscription is not None
            else None
        ),
        can_manage_billing=has_customer,
    )


def _require_billing_mutations(request: Request) -> None:
    if not request.app.state.settings.mutations_enabled:
        raise HTTPException(
            status_code=503, detail="Membership changes are temporarily disabled"
        )


@router.post("/billing/checkout", response_model=RedirectResponse)
@router.post("/api/billing/checkout", response_model=RedirectResponse)
def start_checkout(
    request: Request,
    payload: CheckoutRequest,
    user: User = Depends(get_current_dnd_user),
    account: Account = Depends(get_current_account),
    gateway: BillingGateway = Depends(get_billing_gateway),
    session: Session = Depends(get_request_session),
):
    _require_billing_mutations(request)
    app_settings: Settings = request.app.state.settings
    if active_subscription(session, user.id) is not None:
        raise HTTPException(
            status_code=409,
            detail="You already have PRO. Use Manage billing to change your plan.",
        )
    customer = session.scalar(
        sa.select(BillingCustomer)
        .where(BillingCustomer.user_id == user.id)
        .with_for_update()
    )
    try:
        if customer is None:
            customer = BillingCustomer(
                user_id=user.id,
                stripe_customer_id=gateway.create_customer(
                    email=account.email, user_id=user.id
                ),
            )
            session.add(customer)
            session.commit()
        price_id = (
            app_settings.stripe_price_pro_yearly
            if payload.interval == "year"
            else app_settings.stripe_price_pro_monthly
        )
        url = gateway.create_checkout_session(
            customer_id=customer.stripe_customer_id,
            price_id=price_id,
            user_id=user.id,
            success_url=f"{app_settings.app_public_url}/account?membership=success",
            cancel_url=f"{app_settings.app_public_url}/account?membership=cancelled",
        )
    except Exception as exc:
        session.rollback()
        logger.exception("billing_checkout_failed user_id=%s", user.id)
        raise HTTPException(
            status_code=502, detail="Could not start checkout. Please try again."
        ) from exc
    return RedirectResponse(url=url)


@router.post("/billing/portal", response_model=RedirectResponse)
@router.post("/api/billing/portal", response_model=RedirectResponse)
def open_billing_portal(
    request: Request,
    user: User = Depends(get_current_dnd_user),
    gateway: BillingGateway = Depends(get_billing_gateway),
    session: Session = Depends(get_request_session),
):
    app_settings: Settings = request.app.state.settings
    customer = session.get(BillingCustomer, user.id)
    if customer is None:
        raise HTTPException(status_code=404, detail="No billing account yet")
    try:
        url = gateway.create_portal_session(
            customer_id=customer.stripe_customer_id,
            return_url=f"{app_settings.app_public_url}/account",
        )
    except Exception as exc:
        logger.exception("billing_portal_failed user_id=%s", user.id)
        raise HTTPException(
            status_code=502, detail="Could not open billing. Please try again."
        ) from exc
    return RedirectResponse(url=url)


@router.post("/billing/webhook")
@router.post("/api/billing/webhook")
async def stripe_webhook(
    request: Request,
    gateway: BillingGateway = Depends(get_billing_gateway),
    session: Session = Depends(get_request_session),
):
    signature = request.headers.get("stripe-signature")
    if not signature:
        raise HTTPException(status_code=400, detail="Missing signature")
    payload = await request.body()
    try:
        event = gateway.construct_event(payload, signature)
    except InvalidWebhookError as exc:
        logger.warning("billing_webhook_rejected")
        raise HTTPException(status_code=400, detail="Invalid signature") from exc
    try:
        # Stripe API calls and the database session are blocking.
        await run_in_threadpool(handle_webhook_event, session, gateway, event)
    except Exception as exc:
        session.rollback()
        # A non-2xx response makes Stripe retry the delivery later.
        logger.exception("billing_webhook_failed event_type=%s", event.get("type"))
        raise HTTPException(status_code=500, detail="Webhook not processed") from exc
    return {"received": True}
