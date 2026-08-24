"""Lightweight session notifications with durable deduplication.

The default sender deliberately logs metadata only. A future deployment can
replace it with a real email adapter without changing scheduling semantics.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta
from typing import Protocol

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import (
    ConfirmedSession,
    GroupMembership,
    SessionNotificationDelivery,
    SessionNotificationKind,
    SessionRsvp,
)

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
    today: date,
    days_ahead: int = 7,
    dry_run: bool = False,
    sender: SessionNotificationSender | None = None,
) -> dict[str, int]:
    """Create idempotent upcoming and missing-RSVP reminder deliveries."""
    sender = sender or LoggingSessionNotificationSender()
    sessions = db_session.scalars(
        sa.select(ConfirmedSession)
        .where(
            ConfirmedSession.cancelled_at.is_(None),
            ConfirmedSession.day >= today,
            ConfirmedSession.day <= today + timedelta(days=days_ahead),
        )
        .order_by(ConfirmedSession.day, ConfirmedSession.id)
    ).all()
    counts = {"upcoming": 0, "missing_rsvp": 0}
    for confirmed_session in sessions:
        memberships = db_session.scalars(
            sa.select(GroupMembership).where(
                GroupMembership.group_id == confirmed_session.group_id
            )
        ).all()
        responded = set(
            db_session.scalars(
                sa.select(SessionRsvp.user_id).where(
                    SessionRsvp.session_id == confirmed_session.id
                )
            ).all()
        )
        for membership in memberships:
            kinds = [SessionNotificationKind.UPCOMING_REMINDER]
            if membership.user_id not in responded:
                kinds.append(SessionNotificationKind.MISSING_RSVP_REMINDER)
            for kind in kinds:
                dedupe_key = (
                    f"{kind.value}:{confirmed_session.id}:{membership.user_id}:"
                    f"{confirmed_session.day.isoformat()}"
                )
                exists = db_session.scalar(
                    sa.select(SessionNotificationDelivery.id).where(
                        SessionNotificationDelivery.dedupe_key == dedupe_key
                    )
                )
                if exists:
                    continue
                counter = (
                    "upcoming"
                    if kind == SessionNotificationKind.UPCOMING_REMINDER
                    else "missing_rsvp"
                )
                counts[counter] += 1
                if dry_run:
                    continue
                try:
                    with db_session.begin_nested():
                        db_session.add(
                            SessionNotificationDelivery(
                                session_id=confirmed_session.id,
                                recipient_user_id=membership.user_id,
                                kind=kind,
                                dedupe_key=dedupe_key,
                            )
                        )
                        db_session.flush()
                except IntegrityError:
                    continue
                sender.send(
                    recipient_user_id=membership.user_id,
                    session_id=confirmed_session.id,
                    kind=kind,
                )
    if dry_run:
        db_session.rollback()
    else:
        db_session.commit()
    return counts
