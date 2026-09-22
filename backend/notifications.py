"""Logging-only session events and independent, opt-out personal email reminders."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Protocol

import sqlalchemy as sa
from sqlalchemy.orm import Session

from .email_delivery import (
    EmailDeliveryError,
    ReminderEmail,
    ReminderSender,
    usable_email,
)
from .models import (
    Account,
    ConfirmedSession,
    Group,
    GroupMembership,
    SessionNotificationDelivery,
    SessionNotificationKind,
    SessionRsvp,
    SessionRsvpStatus,
    User,
)
from .session_time import session_utc_range

REMINDER_CHOICES = {
    60: "1 hour before",
    180: "3 hours before",
    720: "12 hours before",
    1440: "1 day before",
    4320: "3 days before",
    10080: "7 days before",
}

logger = logging.getLogger(__name__)


class SessionNotificationSender(Protocol):
    def send(
        self,
        *,
        recipient_user_id: uuid.UUID,
        session_id: uuid.UUID,
        kind: SessionNotificationKind,
    ) -> None: ...


class LoggingSessionNotificationSender:
    """Safe development sender: no address, message body, or secret is logged."""

    def send(
        self,
        *,
        recipient_user_id: uuid.UUID,
        session_id: uuid.UUID,
        kind: SessionNotificationKind,
    ) -> None:
        logger.info(
            "session notification recorded kind=%s session_id=%s recipient_user_id=%s",
            kind.value,
            session_id,
            recipient_user_id,
        )


def _version_key(confirmed_session: ConfirmedSession) -> str:
    version = confirmed_session.updated_at or confirmed_session.confirmed_at
    return version.isoformat()


def record_group_notification(
    db_session: Session,
    *,
    confirmed_session: ConfirmedSession,
    kind: SessionNotificationKind,
    sender: SessionNotificationSender | None = None,
) -> int:
    """Record one notification per group member for a session version."""
    sender = sender or LoggingSessionNotificationSender()
    recipient_ids = db_session.scalars(
        sa.select(GroupMembership.user_id).where(
            GroupMembership.group_id == confirmed_session.group_id
        )
    ).all()
    created = 0
    for recipient_id in recipient_ids:
        dedupe_key = (
            f"{kind.value}:{confirmed_session.id}:{recipient_id}:"
            f"{_version_key(confirmed_session)}"
        )
        if db_session.scalar(
            sa.select(SessionNotificationDelivery.id).where(
                SessionNotificationDelivery.dedupe_key == dedupe_key
            )
        ):
            continue
        db_session.add(
            SessionNotificationDelivery(
                session_id=confirmed_session.id,
                recipient_user_id=recipient_id,
                kind=kind,
                dedupe_key=dedupe_key,
            )
        )
        db_session.flush()
        sender.send(
            recipient_user_id=recipient_id,
            session_id=confirmed_session.id,
            kind=kind,
        )
        created += 1
    return created


def process_session_reminders(
    db_session: Session,
    *,
    now_utc: datetime,
    dry_run: bool = False,
    sender: ReminderSender | None = None,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, int]:
    """Send only due UPCOMING emails; caller serializes runs with the host flock.

    Own a clean worker session. Commit each accepted delivery independently.
    SMTP success followed by a process/commit failure is an at-least-once edge.
    Historical logging rows are never dispatched as emails.
    """
    if now_utc.tzinfo is None or now_utc.utcoffset() is None:
        raise ValueError("now_utc must be an aware datetime")
    if not dry_run and sender is None:
        raise ValueError("Real reminder delivery requires an explicit sender")
    if db_session.new or db_session.dirty or db_session.deleted:
        raise ValueError("Use a clean worker session")
    now_utc = now_utc.astimezone(timezone.utc)
    horizon = now_utc + timedelta(minutes=max(REMINDER_CHOICES))
    # One date margin each side covers all group UTC offsets. Never scan years.
    sessions = db_session.execute(
        sa.select(ConfirmedSession, Group)
        .join(Group, Group.id == ConfirmedSession.group_id)
        .where(
            ConfirmedSession.cancelled_at.is_(None),
            ConfirmedSession.day >= now_utc.date() - timedelta(days=1),
            ConfirmedSession.day <= horizon.date() + timedelta(days=1),
        )
        .order_by(ConfirmedSession.day, ConfirmedSession.id)
    ).all()
    counts = dict.fromkeys(
        (
            "due",
            "sent",
            "skipped_off",
            "skipped_declined",
            "skipped_no_email",
            "skipped_untimed",
            "skipped_invalid_time",
            "not_due",
            "already_delivered",
            "failed",
        ),
        0,
    )
    for confirmed_session, group in sessions:
        if (
            confirmed_session.start_time is None
            or confirmed_session.duration_minutes is None
        ):
            counts["skipped_untimed"] += 1
            continue
        try:
            starts_at, _ = session_utc_range(
                confirmed_session.day,
                confirmed_session.start_time,
                confirmed_session.duration_minutes,
                group.timezone,
            )
        except ValueError:
            counts["skipped_invalid_time"] += 1
            continue
        if starts_at is None or not now_utc < starts_at <= horizon:
            continue
        recipients = db_session.execute(
            sa.select(User, Account.email, SessionRsvp.status)
            .join(GroupMembership, GroupMembership.user_id == User.id)
            .outerjoin(Account, Account.id == User.account_id)
            .outerjoin(
                SessionRsvp,
                sa.and_(
                    SessionRsvp.user_id == User.id,
                    SessionRsvp.session_id == confirmed_session.id,
                ),
            )
            .where(GroupMembership.group_id == group.id)
        ).all()
        for user, account_email, rsvp in recipients:
            current_time = clock() if clock else now_utc
            if current_time.tzinfo is None or current_time.utcoffset() is None:
                raise ValueError("Worker clock must return an aware datetime")
            current_time = current_time.astimezone(timezone.utc)
            if current_time >= starts_at:
                continue
            lead = user.session_reminder_minutes
            if lead is None:
                counts["skipped_off"] += 1
                continue
            if rsvp == SessionRsvpStatus.DECLINED:
                counts["skipped_declined"] += 1
                continue
            recipient = usable_email(account_email)
            if recipient is None:
                counts["skipped_no_email"] += 1
                continue
            if current_time < starts_at - timedelta(minutes=lead):
                counts["not_due"] += 1
                continue
            kind = SessionNotificationKind.UPCOMING_REMINDER
            dedupe_key = f"{kind.value}:{confirmed_session.id}:{user.id}:{starts_at.isoformat()}:{lead}"
            if db_session.scalar(
                sa.select(SessionNotificationDelivery.id).where(
                    SessionNotificationDelivery.dedupe_key == dedupe_key
                )
            ):
                counts["already_delivered"] += 1
                continue
            counts["due"] += 1
            if dry_run:
                continue
            title = confirmed_session.title or "DnD session"
            message = ReminderEmail(
                recipient=recipient,
                subject=f"DnD Planner — Session reminder: {title}",
                body=(
                    f"{title}\n{group.name}\n\n"
                    f"{confirmed_session.day:%A %d %B %Y} at {confirmed_session.start_time:%H:%M}\n"
                    f"{group.timezone}\nDuration: {confirmed_session.duration_minutes} minutes\n\n"
                    "Open DnD Planner:\n"
                    f"https://dnd-planner.dedoo.fr/groups/{group.id}?day={confirmed_session.day.isoformat()}\n\n"
                    f"You received this because your session reminder is set to {REMINDER_CHOICES[lead]}.\n"
                    "Change or disable reminders in Account / Notifications:\n"
                    "https://dnd-planner.dedoo.fr/account\n"
                ),
            )
            try:
                sender.send(message)
            except EmailDeliveryError:
                counts["failed"] += 1
                continue
            db_session.add(
                SessionNotificationDelivery(
                    session_id=confirmed_session.id,
                    recipient_user_id=user.id,
                    kind=kind,
                    dedupe_key=dedupe_key,
                    delivered_at=current_time,
                )
            )
            # Do not swallow DB failure after SMTP acceptance; fail visibly and
            # allow a later run to retry (the documented narrow duplicate edge).
            db_session.commit()
            counts["sent"] += 1
    db_session.rollback()  # end read transactions; dry runs have written nothing
    return counts
