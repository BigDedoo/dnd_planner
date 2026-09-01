"""Temporary, explicit legacy-profile recovery transaction helpers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import (
    Account,
    Group,
    GroupMembership,
    LegacyProfileRecovery,
    User,
)


class LegacyProfileRecoveryError(Exception):
    """Base class for expected recovery conflicts."""


class AccountAlreadyLinkedError(LegacyProfileRecoveryError):
    """The authenticated account already owns a different DnD profile."""


class RecoveryProfileNotFoundError(LegacyProfileRecoveryError):
    """The requested user was never made explicitly recoverable."""


class RecoveryProfileClaimedError(LegacyProfileRecoveryError):
    """Another account has already claimed the recovery profile."""


@dataclass(frozen=True)
class AvailableRecoveryProfile:
    user_id: uuid.UUID
    display_name: str
    group_names: tuple[str, ...]


def list_available_recovery_profiles(
    session: Session,
    account_id: uuid.UUID,
) -> list[AvailableRecoveryProfile]:
    if session.scalar(select(User.id).where(User.account_id == account_id)) is not None:
        raise AccountAlreadyLinkedError

    rows = session.execute(
        select(LegacyProfileRecovery.user_id, User.display_name, Group.name)
        .join(User, User.id == LegacyProfileRecovery.user_id)
        .outerjoin(GroupMembership, GroupMembership.user_id == User.id)
        .outerjoin(Group, Group.id == GroupMembership.group_id)
        .where(
            LegacyProfileRecovery.claimed_at.is_(None),
            LegacyProfileRecovery.claimed_by_account_id.is_(None),
        )
        .order_by(func.lower(User.display_name), User.id, func.lower(Group.name))
    ).all()

    profiles: dict[uuid.UUID, tuple[str, list[str]]] = {}
    for user_id, display_name, group_name in rows:
        profile = profiles.setdefault(user_id, (display_name, []))
        if group_name is not None and group_name not in profile[1]:
            profile[1].append(group_name)
    return [
        AvailableRecoveryProfile(
            user_id=user_id,
            display_name=display_name,
            group_names=tuple(group_names),
        )
        for user_id, (display_name, group_names) in profiles.items()
    ]


def claim_legacy_profile(
    session: Session,
    account_id: uuid.UUID,
    user_id: uuid.UUID,
) -> User:
    """Atomically move one explicitly eligible User to an unlinked Account."""
    try:
        account = session.scalar(
            select(Account).where(Account.id == account_id).with_for_update()
        )
        if account is None:
            raise AccountAlreadyLinkedError

        existing_user = session.scalar(
            select(User).where(User.account_id == account_id).with_for_update()
        )
        if existing_user is not None and existing_user.id != user_id:
            raise AccountAlreadyLinkedError

        recovery = session.scalar(
            select(LegacyProfileRecovery)
            .where(LegacyProfileRecovery.user_id == user_id)
            .with_for_update()
        )
        if existing_user is not None:
            if (
                recovery is not None
                and recovery.claimed_at is not None
                and recovery.claimed_by_account_id == account_id
            ):
                session.commit()
                return existing_user
            raise AccountAlreadyLinkedError
        if recovery is None:
            raise RecoveryProfileNotFoundError
        if recovery.claimed_at is not None:
            raise RecoveryProfileClaimedError

        user = session.scalar(select(User).where(User.id == user_id).with_for_update())
        if user is None:
            raise RecoveryProfileNotFoundError

        user.account_id = account.id
        recovery.claimed_at = datetime.now(timezone.utc)
        recovery.claimed_by_account_id = account.id
        session.flush()
        session.commit()
        return user
    except IntegrityError as exc:
        session.rollback()
        linked_user = session.scalar(select(User).where(User.account_id == account_id))
        recovery = session.get(LegacyProfileRecovery, user_id)
        if (
            linked_user is not None
            and linked_user.id == user_id
            and recovery is not None
            and recovery.claimed_by_account_id == account_id
        ):
            return linked_user
        if linked_user is not None:
            raise AccountAlreadyLinkedError from exc
        raise RecoveryProfileClaimedError from exc
    except Exception:
        session.rollback()
        raise
