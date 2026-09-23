"""Transactional session-event email outbox and bounded asynchronous delivery."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

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
    SessionEventEmailOutbox,
    SessionNotificationDelivery,
    SessionNotificationKind,
    User,
)

EVENT_KINDS = frozenset(
    {
        SessionNotificationKind.SCHEDULED,
        SessionNotificationKind.CHANGED,
        SessionNotificationKind.CANCELLED,
    }
)


def session_details_snapshot(
    event: ConfirmedSession,
) -> tuple[str | None, object, int | None]:
    return event.title, event.start_time, event.duration_minutes


def _when(event: ConfirmedSession, group: Group) -> str:
    day = event.day.strftime("%A %d %B %Y")
    if event.start_time is None:
        return f"{day}\nTime not set\n{group.timezone}"
    return f"{day} at {event.start_time:%H:%M}\n{group.timezone}"


def _value(value: object, *, is_time: bool = False) -> str:
    if value is None:
        return "Not set"
    if is_time:
        return value.strftime("%H:%M")
    return str(value)


def event_email_content(
    event: ConfirmedSession,
    group: Group,
    kind: SessionNotificationKind,
    *,
    before: tuple[str | None, object, int | None] | None = None,
) -> tuple[str, str]:
    """Snapshot only public session details; never include notes or recipients."""
    if kind not in EVENT_KINDS:
        raise ValueError("Unsupported lifecycle email kind")
    title = event.title or "DnD session"
    link = f"https://dnd-planner.dedoo.fr/groups/{group.id}?day={event.day.isoformat()}"
    footer = f"\nOpen DnD Planner:\n{link}\n\nChange important session emails in Account / Notifications.\n"
    if kind == SessionNotificationKind.SCHEDULED:
        duration = (
            f"\nDuration: {event.duration_minutes} minutes"
            if event.duration_minutes is not None
            else ""
        )
        return (
            f"DnD Planner — Session scheduled: {title}",
            f"{title}\n{group.name}\n\n{_when(event, group)}{duration}\n{footer}",
        )
    if kind == SessionNotificationKind.CANCELLED:
        return (
            f"DnD Planner — Session cancelled: {title}",
            f"{title}\n{group.name}\n\nThe session scheduled for:\n"
            f"{_when(event, group)}\n\nhas been cancelled.\n{footer}",
        )
    if before is None:
        raise ValueError("Changed email requires the previous details")
    after = session_details_snapshot(event)
    labels = ("Title", "Time", "Duration")
    changes = []
    for index, (old, new) in enumerate(zip(before, after)):
        if old != new:
            old_text = _value(old, is_time=index == 1)
            new_text = _value(new, is_time=index == 1)
            if index == 2:
                old_text += " min" if old is not None else ""
                new_text += " min" if new is not None else ""
            changes.append(f"{labels[index]}: {old_text} -> {new_text}")
    if not changes:
        raise ValueError("Changed email requires a meaningful change")
    return (
        f"DnD Planner — Session changed: {title}",
        f"{title}\n{group.name}\n\n"
        + "\n".join(changes)
        + f"\n\nSession:\n{_when(event, group)}\n{footer}",
    )


def enqueue_session_event_emails(
    session: Session,
    *,
    event: ConfirmedSession,
    group: Group,
    kind: SessionNotificationKind,
    actor_user_id: uuid.UUID,
    before: tuple[str | None, object, int | None] | None = None,
) -> int:
    """Add pending rows to the caller's session; never commit or contact SMTP."""
    subject, body = event_email_content(event, group, kind, before=before)
    recipients = session.scalars(
        sa.select(User)
        .join(GroupMembership, GroupMembership.user_id == User.id)
        .join(Account, Account.id == User.account_id)
        .where(
            GroupMembership.group_id == group.id,
            User.id != actor_user_id,
            User.important_session_emails_enabled.is_(True),
        )
    ).all()
    event_id = uuid.uuid4()
    created_at = datetime.now(timezone.utc)
    for user in recipients:
        session.add(
            SessionEventEmailOutbox(
                id=uuid.uuid4(),
                session_id=event.id,
                recipient_user_id=user.id,
                kind=kind,
                dedupe_key=f"email:{kind.value}:{event.id}:{user.id}:{event_id}",
                subject=subject,
                body=body,
                created_at=created_at,
                next_attempt_at=created_at,
            )
        )
    return len(recipients)


def _retry_delay(attempt_count: int) -> timedelta:
    minutes = (1, 5, 15)
    return timedelta(minutes=minutes[attempt_count - 1] if attempt_count <= 3 else 60)


def process_session_event_emails(
    session: Session,
    *,
    now_utc: datetime,
    dry_run: bool = False,
    sender: ReminderSender | None = None,
    batch_size: int = 50,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, int]:
    """Process oldest due work, with current recipient checks and capped retries.

    Each accepted email is committed with its delivery row and outbox deletion.
    SMTP acceptance followed by process/DB failure has an at-least-once edge.
    """
    if now_utc.tzinfo is None or now_utc.utcoffset() is None:
        raise ValueError("now_utc must be aware")
    if not dry_run and sender is None:
        raise ValueError("Real delivery requires an explicit sender")
    if not 1 <= batch_size <= 100:
        raise ValueError("batch_size must be between 1 and 100")
    if session.new or session.dirty or session.deleted:
        raise ValueError("Use a clean worker session")
    now_utc = now_utc.astimezone(timezone.utc)
    row_ids = session.scalars(
        sa.select(SessionEventEmailOutbox.id)
        .where(SessionEventEmailOutbox.next_attempt_at <= now_utc)
        .order_by(SessionEventEmailOutbox.created_at, SessionEventEmailOutbox.id)
        .limit(batch_size)
    ).all()
    counts = dict.fromkeys(
        ("pending", "sent", "discarded", "failed", "blocked_order"), 0
    )
    counts["pending"] = len(row_ids)
    for row_id in row_ids:
        row = session.get(SessionEventEmailOutbox, row_id)
        if row is None:
            continue
        # Do not overtake an older retry for the same user and session.
        earlier = session.scalar(
            sa.select(SessionEventEmailOutbox.id)
            .where(
                SessionEventEmailOutbox.recipient_user_id == row.recipient_user_id,
                SessionEventEmailOutbox.session_id == row.session_id,
                sa.or_(
                    SessionEventEmailOutbox.created_at < row.created_at,
                    sa.and_(
                        SessionEventEmailOutbox.created_at == row.created_at,
                        SessionEventEmailOutbox.id < row.id,
                    ),
                ),
            )
            .limit(1)
        )
        if earlier is not None:
            counts["blocked_order"] += 1
            continue
        recipient = session.execute(
            sa.select(User, Account.email)
            .join(Account, Account.id == User.account_id)
            .join(GroupMembership, GroupMembership.user_id == User.id)
            .join(ConfirmedSession, ConfirmedSession.id == row.session_id)
            .where(
                User.id == row.recipient_user_id,
                GroupMembership.group_id == ConfirmedSession.group_id,
                User.important_session_emails_enabled.is_(True),
            )
        ).first()
        address = usable_email(recipient[1]) if recipient else None
        if address is None:
            counts["discarded"] += 1
            if not dry_run:
                session.delete(row)
                session.commit()
            continue
        if dry_run:
            continue
        try:
            sender.send(
                ReminderEmail(recipient=address, subject=row.subject, body=row.body)
            )
        except EmailDeliveryError:
            row.attempt_count += 1
            current = clock() if clock else datetime.now(timezone.utc)
            row.next_attempt_at = current.astimezone(timezone.utc) + _retry_delay(
                row.attempt_count
            )
            session.commit()
            counts["failed"] += 1
            continue
        session.add(
            SessionNotificationDelivery(
                session_id=row.session_id,
                recipient_user_id=row.recipient_user_id,
                kind=row.kind,
                dedupe_key=row.dedupe_key,
                delivered_at=(clock() if clock else datetime.now(timezone.utc)),
            )
        )
        session.delete(row)
        session.commit()
        counts["sent"] += 1
    session.rollback()
    return counts
