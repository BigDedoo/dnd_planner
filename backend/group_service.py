from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Session

from .models import (
    ConfirmedSession,
    Group,
    GroupInvite,
    GroupMembership,
    MembershipRole,
    SessionNotificationDelivery,
    SessionRsvp,
    User,
)


class GroupServiceError(ValueError):
    """Base error for group ownership and membership rules."""


class GroupNotFoundError(GroupServiceError):
    pass


class MembershipNotFoundError(GroupServiceError):
    pass


class OwnerInvariantError(GroupServiceError):
    pass


def _require_transaction(session: Session) -> None:
    if not session.in_transaction():
        raise GroupServiceError(
            "Group mutations require an explicit caller-owned transaction"
        )


def _lock_group(session: Session, group_id: uuid.UUID) -> Group:
    group = session.scalar(
        sa.select(Group).where(Group.id == group_id).with_for_update()
    )
    if group is None:
        raise GroupNotFoundError("Group does not exist")
    return group


def _get_membership(
    session: Session,
    group_id: uuid.UUID,
    user_id: uuid.UUID,
) -> GroupMembership:
    membership = session.get(
        GroupMembership,
        {"group_id": group_id, "user_id": user_id},
    )
    if membership is None:
        raise MembershipNotFoundError("User is not a member of the group")
    return membership


def _verify_exactly_one_owner(session: Session, group_id: uuid.UUID) -> None:
    owner_count = session.scalar(
        sa.select(sa.func.count())
        .select_from(GroupMembership)
        .where(
            GroupMembership.group_id == group_id,
            GroupMembership.role == MembershipRole.OWNER,
        )
    )
    if owner_count != 1:
        raise OwnerInvariantError("Group must have exactly one owner")


def create_group_with_owner(
    session: Session,
    *,
    name: str,
    owner_user_id: uuid.UUID,
    timezone: str = "UTC",
    description: str | None = None,
) -> Group:
    """Create a group and owner inside the caller's active transaction."""
    _require_transaction(session)
    if session.get(User, owner_user_id) is None:
        raise MembershipNotFoundError("Owner user does not exist")

    group = Group(name=name, timezone=timezone, description=description)
    session.add(group)
    session.flush()
    session.add(
        GroupMembership(
            group_id=group.id,
            user_id=owner_user_id,
            role=MembershipRole.OWNER,
            display_order=0,
        )
    )
    session.flush()
    _verify_exactly_one_owner(session, group.id)
    return group


def transfer_ownership(
    session: Session,
    *,
    group_id: uuid.UUID,
    current_owner_user_id: uuid.UUID,
    new_owner_user_id: uuid.UUID,
) -> None:
    """Transfer ownership atomically inside the caller's active transaction."""
    _require_transaction(session)
    _lock_group(session, group_id)
    current_owner = _get_membership(session, group_id, current_owner_user_id)
    if current_owner.role != MembershipRole.OWNER:
        raise OwnerInvariantError("Current owner does not match the group owner")

    new_owner = _get_membership(session, group_id, new_owner_user_id)
    if current_owner_user_id == new_owner_user_id:
        _verify_exactly_one_owner(session, group_id)
        return

    current_owner.role = MembershipRole.MEMBER
    session.flush()
    new_owner.role = MembershipRole.OWNER
    session.flush()
    _verify_exactly_one_owner(session, group_id)


def remove_member(
    session: Session,
    *,
    group_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    """Remove a nonowner while preserving one owner."""
    _require_transaction(session)
    _lock_group(session, group_id)
    membership = _get_membership(session, group_id, user_id)
    if membership.role == MembershipRole.OWNER:
        raise OwnerInvariantError(
            "The owner must transfer ownership before leaving the group"
        )
    session.delete(membership)
    session.flush()
    _verify_exactly_one_owner(session, group_id)


def delete_group(session: Session, *, group_id: uuid.UUID) -> None:
    """Delete a whole group inside the caller's active transaction."""
    _require_transaction(session)
    group = _lock_group(session, group_id)
    # PostgreSQL enforces the database cascades. Delete explicitly as well so the
    # legacy SQLite runtime keeps the same cleanup semantics when foreign-key
    # enforcement has not been enabled on a connection.
    session.execute(sa.delete(GroupInvite).where(GroupInvite.group_id == group.id))
    session.execute(
        sa.delete(SessionNotificationDelivery).where(
            SessionNotificationDelivery.session_id.in_(
                sa.select(ConfirmedSession.id).where(
                    ConfirmedSession.group_id == group.id
                )
            )
        )
    )
    session.execute(
        sa.delete(SessionRsvp).where(
            SessionRsvp.session_id.in_(
                sa.select(ConfirmedSession.id).where(
                    ConfirmedSession.group_id == group.id
                )
            )
        )
    )
    session.execute(
        sa.delete(ConfirmedSession).where(ConfirmedSession.group_id == group.id)
    )
    session.execute(
        sa.delete(GroupMembership).where(GroupMembership.group_id == group.id)
    )
    session.delete(group)
    session.flush()
