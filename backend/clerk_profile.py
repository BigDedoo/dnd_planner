"""Optional Clerk profile enrichment for stable internal accounts."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import sqlalchemy as sa
from clerk_backend_api import Clerk
from clerk_backend_api.models import User as ClerkUser
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import Account

logger = logging.getLogger(__name__)

PROFILE_REFRESH_INTERVAL = timedelta(hours=24)


@dataclass(frozen=True)
class ClerkProfile:
    """Non-authoritative human-readable metadata from Clerk."""

    email: str | None
    username: str | None
    display_name: str | None


class ClerkProfileClient(Protocol):
    def fetch_profile(self, clerk_user_id: str) -> ClerkProfile: ...


def _normalized_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized or None


def _is_verified(value: object) -> bool:
    status = getattr(value, "status", None)
    return getattr(status, "value", status) == "verified"


def _primary_verified_email(user: Any) -> str | None:
    primary_id = _normalized_text(getattr(user, "primary_email_address_id", None))
    if primary_id is None:
        return None
    for address in getattr(user, "email_addresses", []) or []:
        if getattr(address, "id", None) != primary_id:
            continue
        if not _is_verified(getattr(address, "verification", None)):
            return None
        email = _normalized_text(getattr(address, "email_address", None))
        return email.lower() if email else None
    return None


def _verified_external_username(account: Any) -> str | None:
    if not _is_verified(getattr(account, "verification", None)):
        return None
    return _normalized_text(getattr(account, "username", None))


def _external_username(user: Any) -> str | None:
    verified_social: list[tuple[str, str]] = []
    for external_account in getattr(user, "external_accounts", []) or []:
        username = _verified_external_username(external_account)
        provider = _normalized_text(getattr(external_account, "provider", None))
        if username is None or provider is None:
            continue
        normalized_provider = provider.casefold()
        if "discord" in normalized_provider:
            return username
        verified_social.append((normalized_provider, username))
    if not verified_social:
        return None
    verified_social.sort(key=lambda item: item[0])
    return verified_social[0][1]


def extract_clerk_profile(user: ClerkUser | Any) -> ClerkProfile:
    """Extract only verified and useful profile metadata from a Clerk user."""
    username = _normalized_text(getattr(user, "username", None))
    if username is None:
        username = _external_username(user)

    display_name = _normalized_text(getattr(user, "full_name", None))
    if display_name is None:
        first_name = _normalized_text(getattr(user, "first_name", None))
        last_name = _normalized_text(getattr(user, "last_name", None))
        display_name = _normalized_text(
            " ".join(part for part in (first_name, last_name) if part)
        )
    if display_name is None:
        display_name = username

    return ClerkProfile(
        email=_primary_verified_email(user),
        username=username,
        display_name=display_name,
    )


class ClerkSDKProfileClient:
    """Retrieve Backend Users through clerk-backend-api 6.0.1."""

    def __init__(self, secret_key: str) -> None:
        self._client = Clerk(bearer_auth=secret_key)

    def fetch_profile(self, clerk_user_id: str) -> ClerkProfile:
        user = self._client.users.get(user_id=clerk_user_id)
        return extract_clerk_profile(user)


def profile_sync_is_due(
    account: Account,
    now: datetime | None = None,
) -> bool:
    """Bound profile refreshes to at most once per 24 hours after success."""
    if account.profile_synced_at is None:
        return True
    current_time = now or datetime.now(timezone.utc)
    synced_at = account.profile_synced_at
    if synced_at.tzinfo is None:
        synced_at = synced_at.replace(tzinfo=timezone.utc)
    return current_time - synced_at >= PROFILE_REFRESH_INTERVAL


def _email_is_owned_by_another_account(
    session: Session,
    account: Account,
    email: str,
) -> bool:
    owner_id = session.scalar(
        sa.select(Account.id).where(
            Account.id != account.id,
            sa.func.lower(Account.email) == email.casefold(),
        )
    )
    return owner_id is not None


def apply_clerk_profile(
    session: Session,
    account: Account,
    profile: ClerkProfile,
    synced_at: datetime | None = None,
) -> Account:
    """Persist a Clerk profile without merging accounts on email collisions."""
    account.username = profile.username
    account.display_name = profile.display_name
    session.flush()

    previous_email = account.email
    if profile.email is None:
        account.email = None
    elif _email_is_owned_by_another_account(session, account, profile.email):
        logger.warning("clerk_profile_email_conflict account_id=%s", account.id)
    else:
        savepoint = session.begin_nested()
        try:
            account.email = profile.email
            session.flush()
            savepoint.commit()
        except IntegrityError:
            savepoint.rollback()
            account.email = previous_email
            logger.warning("clerk_profile_email_conflict account_id=%s", account.id)

    account.profile_synced_at = synced_at or datetime.now(timezone.utc)
    session.commit()
    return account


def sync_account_profile_if_due(
    session: Session,
    account: Account,
    clerk_user_id: str,
    profile_client: ClerkProfileClient,
    now: datetime | None = None,
) -> Account:
    """Best-effort profile synchronization after authentication has succeeded."""
    if not profile_sync_is_due(account, now=now):
        return account

    try:
        profile = profile_client.fetch_profile(clerk_user_id)
    except Exception:
        logger.warning("clerk_profile_fetch_failed account_id=%s", account.id)
        return account

    try:
        account = apply_clerk_profile(
            session,
            account,
            profile,
            synced_at=now,
        )
    except Exception:
        session.rollback()
        logger.warning("clerk_profile_persist_failed account_id=%s", account.id)
        restored = session.get(Account, account.id)
        return restored or account

    logger.info("clerk_profile_synced account_id=%s", account.id)
    return account
