"""Personal exports and the operator-only, transactional departure operation."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Session

from .models import (
    Account,
    AccountIdentity,
    Availability,
    ConfirmedSession,
    Group,
    GroupInvite,
    GroupMembership,
    LegacyProfileRecovery,
    MembershipRole,
    SessionNotificationDelivery,
    SessionRsvp,
    User,
)


def _fields(record: object, *names: str) -> dict:
    return {name: getattr(record, name) for name in names}


def export_account_data(session: Session, account: Account) -> dict:
    """Explicit field allowlists; never serialize ORM relationships or identities."""
    user = session.scalar(sa.select(User).where(User.account_id == account.id))
    result = {
        "schema_version": 2,
        "exported_at": datetime.now(timezone.utc),
        "account": _fields(
            account,
            "id",
            "email",
            "username",
            "display_name",
            "created_at",
            "updated_at",
        ),
        "profile": None,
        "memberships": [],
        "availability": [],
        "rsvps": [],
        "created_invites": [],
        "notifications": [],
    }
    if user is None:
        return result
    result["profile"] = _fields(
        user,
        "id",
        "email",
        "display_name",
        "timezone",
        "session_reminder_minutes",
        "created_at",
        "updated_at",
    )
    result["memberships"] = [
        {**_fields(m, "group_id", "role", "nickname", "joined_at"), "group_name": name}
        for m, name in session.execute(
            sa.select(GroupMembership, Group.name)
            .join(Group, Group.id == GroupMembership.group_id)
            .where(GroupMembership.user_id == user.id)
            .order_by(GroupMembership.group_id)
        )
    ]
    result["availability"] = [
        _fields(row, "day", "status", "updated_at")
        for row in session.scalars(
            sa.select(Availability)
            .where(Availability.user_id == user.id)
            .order_by(Availability.day)
        )
    ]
    result["rsvps"] = [
        {
            **_fields(rsvp, "session_id", "status", "responded_at"),
            "group_id": event.group_id,
            "group_name": name,
            "session_day": event.day,
            "session_title": event.title,
        }
        for rsvp, event, name in session.execute(
            sa.select(SessionRsvp, ConfirmedSession, Group.name)
            .join(ConfirmedSession, ConfirmedSession.id == SessionRsvp.session_id)
            .join(Group, Group.id == ConfirmedSession.group_id)
            .where(SessionRsvp.user_id == user.id)
            .order_by(ConfirmedSession.day, ConfirmedSession.id)
        )
    ]
    result["created_invites"] = [
        {
            **_fields(row, "id", "group_id", "created_at", "revoked_at", "use_count"),
            "group_name": name,
        }
        for row, name in session.execute(
            sa.select(GroupInvite, Group.name)
            .join(Group, Group.id == GroupInvite.group_id)
            .where(GroupInvite.created_by_user_id == user.id)
            .order_by(GroupInvite.created_at, GroupInvite.id)
        )
    ]
    result["notifications"] = [
        _fields(row, "session_id", "kind", "delivered_at")
        for row in session.scalars(
            sa.select(SessionNotificationDelivery)
            .where(SessionNotificationDelivery.recipient_user_id == user.id)
            .order_by(
                SessionNotificationDelivery.delivered_at, SessionNotificationDelivery.id
            )
        )
    ]
    return result


class AccountDeletionError(ValueError):
    """Safe operator-facing failure, never a database driver message."""


def _verify_dependency_graph(session: Session) -> None:
    # A new FK may otherwise silently cascade personal or shared data. Fail
    # closed until the operator workflow is explicitly reviewed for that schema.
    # Keep this reviewed list explicit: adding an ORM model must not implicitly
    # authorize cascading away its data during an account deletion.
    expected = {
        (table, (column,), target, ("id",), action)
        for table, column, target, action in [
            ("users", "account_id", "accounts", "SET NULL"),
            ("account_identities", "account_id", "accounts", "CASCADE"),
            ("group_memberships", "user_id", "users", "RESTRICT"),
            ("availability", "user_id", "users", "CASCADE"),
            ("confirmed_sessions", "confirmed_by_user_id", "users", "RESTRICT"),
            ("confirmed_sessions", "cancelled_by_user_id", "users", "RESTRICT"),
            ("confirmed_session_rsvps", "user_id", "users", "RESTRICT"),
            (
                "session_notification_deliveries",
                "recipient_user_id",
                "users",
                "RESTRICT",
            ),
            ("group_invites", "created_by_user_id", "users", "RESTRICT"),
            ("legacy_profile_recoveries", "user_id", "users", "CASCADE"),
            (
                "legacy_profile_recoveries",
                "claimed_by_account_id",
                "accounts",
                "RESTRICT",
            ),
        ]
    }
    deletion_targets = {
        "accounts",
        "users",
        "account_identities",
        "group_memberships",
        "availability",
        "confirmed_session_rsvps",
        "session_notification_deliveries",
        "group_invites",
        "legacy_profile_recoveries",
    }
    inspector = sa.inspect(session.connection())
    actual = {
        (
            table,
            tuple(fk["constrained_columns"]),
            fk["referred_table"],
            tuple(fk["referred_columns"]),
            fk.get("options", {}).get("ondelete"),
        )
        for table in inspector.get_table_names()
        for fk in inspector.get_foreign_keys(table)
        if fk["referred_table"] in deletion_targets
    }
    if actual != expected:
        raise AccountDeletionError(
            "Unexpected account/user dependencies; no data changed."
        )


def delete_account_data(
    session: Session, account_id: uuid.UUID, *, apply: bool = False
) -> dict:
    """Own one fresh transaction. Dry-run reads only; apply commits or rolls back all."""
    if session.in_transaction():
        raise AccountDeletionError("Deletion requires a fresh dedicated session.")
    try:
        with session.begin():
            _verify_dependency_graph(session)
            account = session.scalar(
                sa.select(Account).where(Account.id == account_id).with_for_update()
            )
            if account is None:
                raise AccountDeletionError(
                    "Account UUID does not exist; no data changed."
                )
            user = session.scalar(
                sa.select(User).where(User.account_id == account_id).with_for_update()
            )
            memberships = (
                []
                if user is None
                else list(
                    session.scalars(
                        sa.select(GroupMembership)
                        .where(GroupMembership.user_id == user.id)
                        .order_by(GroupMembership.group_id)
                        .with_for_update()
                    )
                )
            )
            owners = sum(m.role == MembershipRole.OWNER for m in memberships)
            filters = {
                "identities": (
                    AccountIdentity,
                    AccountIdentity.account_id == account_id,
                ),
                "legacy_recovery_links": (
                    LegacyProfileRecovery,
                    sa.or_(
                        LegacyProfileRecovery.claimed_by_account_id == account_id,
                        LegacyProfileRecovery.user_id == user.id
                        if user
                        else sa.false(),
                    ),
                ),
            }
            if user:
                filters.update(
                    {
                        "availability": (Availability, Availability.user_id == user.id),
                        "rsvps": (SessionRsvp, SessionRsvp.user_id == user.id),
                        "notifications": (
                            SessionNotificationDelivery,
                            SessionNotificationDelivery.recipient_user_id == user.id,
                        ),
                        "created_invites": (
                            GroupInvite,
                            GroupInvite.created_by_user_id == user.id,
                        ),
                    }
                )
            counts = {
                name: session.scalar(
                    sa.select(sa.func.count()).select_from(model).where(condition)
                )
                for name, (model, condition) in filters.items()
            }
            historical = (
                0
                if user is None
                else session.scalar(
                    sa.select(sa.func.count())
                    .select_from(ConfirmedSession)
                    .where(
                        sa.or_(
                            ConfirmedSession.confirmed_by_user_id == user.id,
                            ConfirmedSession.cancelled_by_user_id == user.id,
                        )
                    )
                )
            )
            summary = {
                "account_id": str(account_id),
                "user_id": str(user.id) if user else None,
                "memberships": len(memberships),
                "owned_groups": owners,
                **counts,
                "historical_sessions": historical,
                "retain_anonymized_user": bool(historical),
                "blocker": "Transfer ownership or delete owned groups first."
                if owners
                else None,
                "applied": False,
            }
            if not apply:
                return summary
            if owners:
                raise AccountDeletionError(summary["blocker"])
            for model, condition in filters.values():
                session.execute(sa.delete(model).where(condition))
            if user:
                session.execute(
                    sa.delete(GroupMembership).where(GroupMembership.user_id == user.id)
                )
                if historical:
                    user.account_id = None
                    user.auth_provider = None
                    user.auth_subject = None
                    user.email = None
                    user.display_name = "Deleted user"
                    user.timezone = "UTC"
                    user.session_reminder_minutes = None
                    session.flush()
                else:
                    session.execute(sa.delete(User).where(User.id == user.id))
            session.execute(sa.delete(Account).where(Account.id == account_id))
            summary["applied"] = True
        return summary
    except AccountDeletionError:
        raise
    except Exception:
        # No driver exception text/SQL parameters: these can contain credentials
        # or personal data. The transaction context has already rolled back.
        raise AccountDeletionError(
            "Deletion failed; all changes were rolled back."
        ) from None
