from __future__ import annotations

import uuid
from datetime import date, time, timedelta, timezone
from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from backend.account_data import delete_account_data, export_account_data
from backend.email_delivery import EmailDeliveryError
from backend.models import (
    Account,
    ConfirmedSession,
    Group,
    GroupMembership,
    SessionEventEmailOutbox,
    SessionNotificationDelivery,
    SessionNotificationKind,
    SessionRsvp,
    SessionRsvpStatus,
    User,
)
from backend.session_event_emails import (
    enqueue_session_event_emails,
    event_email_content,
    process_session_event_emails,
)
from backend.tests.test_account_data import (
    export_client,
    lifecycle_engine,
    seed_personal_data,
)

__all__ = ["export_client", "lifecycle_engine"]
HEADERS = {"Authorization": "Bearer private-session-token"}
DAY = "2026-10-06"


def _outbox(session):
    return session.scalars(
        sa.select(SessionEventEmailOutbox).order_by(SessionEventEmailOutbox.created_at)
    ).all()


def _create(client, group_id):
    return client.put(
        f"/api/groups/{group_id}/confirmed-sessions/{DAY}",
        headers=HEADERS,
        json={"title": "Dragon hunt", "start_time": "20:00", "duration_minutes": 180},
    )


def test_scheduled_actor_excluded_opt_out_and_idempotence(
    lifecycle_engine, export_client, monkeypatch
):
    ids = seed_personal_data(lifecycle_engine, owner=True)

    # API mutations must not touch SMTP, even if the transport is unavailable.
    def unavailable_smtp(*_args, **_kwargs):
        raise RuntimeError("synthetic SMTP outage")

    monkeypatch.setattr(
        "backend.email_delivery.SmtpReminderSender.send", unavailable_smtp
    )
    with Session(lifecycle_engine) as session:
        # Other is the sole non-actor recipient. Declined RSVP never suppresses
        # a lifecycle email; the personal reminder rule is separate.
        assert session.get(User, ids["other"]).important_session_emails_enabled is True
        old_delivery_count = session.scalar(
            sa.select(sa.func.count()).select_from(SessionNotificationDelivery)
        )
    assert _create(export_client, ids["group"]).status_code == 200
    assert _create(export_client, ids["group"]).status_code == 200
    with Session(lifecycle_engine) as session:
        rows = _outbox(session)
        assert len(rows) == 1
        assert rows[0].kind == SessionNotificationKind.SCHEDULED
        assert rows[0].recipient_user_id == ids["other"]
        assert "Dragon hunt" in rows[0].subject
        assert "Shared campaign" in rows[0].body
        assert "Tuesday 06 October 2026 at 20:00" in rows[0].body
        assert "Duration: 180 minutes" in rows[0].body
        assert f"/groups/{ids['group']}?day={DAY}" in rows[0].body
        assert "notes" not in rows[0].body.lower()
        assert (
            session.scalar(
                sa.select(sa.func.count()).select_from(SessionNotificationDelivery)
            )
            == old_delivery_count
        )


def test_recipient_filters_and_preferences_are_independent(
    lifecycle_engine, export_client
):
    ids = seed_personal_data(lifecycle_engine, owner=True)
    with Session(lifecycle_engine) as session:
        other = session.get(User, ids["other"])
        other.session_reminder_minutes = None
        session.commit()
    response = export_client.patch(
        "/api/me/notification-preferences",
        headers=HEADERS,
        json={"important_session_emails_enabled": False},
    )
    assert response.status_code == 200
    assert response.json() == {
        "session_reminder_minutes": 1440,
        "important_session_emails_enabled": False,
    }
    with Session(lifecycle_engine) as session:
        # Disable the recipient rather than the actor.
        session.get(User, ids["other"]).important_session_emails_enabled = False
        session.commit()
    assert _create(export_client, ids["group"]).status_code == 200
    with Session(lifecycle_engine) as session:
        assert _outbox(session) == []
        other = session.get(User, ids["other"])
        other.important_session_emails_enabled = True
        other.account_id = None
        session.commit()
    # Reconfirm a cancelled event to exercise the same eligibility filter.
    assert (
        export_client.delete(
            f"/api/groups/{ids['group']}/confirmed-sessions/{DAY}", headers=HEADERS
        ).status_code
        == 200
    )
    assert _create(export_client, ids["group"]).status_code == 200
    with Session(lifecycle_engine) as session:
        assert _outbox(session) == []


def test_changed_only_for_meaningful_fields_and_cancel_once(
    lifecycle_engine, export_client
):
    ids = seed_personal_data(lifecycle_engine, owner=True)
    assert _create(export_client, ids["group"]).status_code == 200
    url = f"/api/groups/{ids['group']}/confirmed-sessions/{DAY}"
    assert (
        export_client.patch(
            url, headers=HEADERS, json={"notes": "Bring dice"}
        ).status_code
        == 200
    )
    assert (
        export_client.patch(
            url, headers=HEADERS, json={"title": "Dragon hunt"}
        ).status_code
        == 200
    )
    with Session(lifecycle_engine) as session:
        assert len(_outbox(session)) == 1
    assert (
        export_client.patch(
            url,
            headers=HEADERS,
            json={
                "title": "Castle raid",
                "start_time": "21:00",
                "duration_minutes": 240,
            },
        ).status_code
        == 200
    )
    with Session(lifecycle_engine) as session:
        rows = _outbox(session)
        assert len(rows) == 2
        changed = next(
            row for row in rows if row.kind == SessionNotificationKind.CHANGED
        )
        assert "Title: Dragon hunt -> Castle raid" in changed.body
        assert "Time: 20:00 -> 21:00" in changed.body
        assert "Duration: 180 min -> 240 min" in changed.body
        assert "Bring dice" not in changed.body
    assert export_client.delete(url, headers=HEADERS).status_code == 200
    assert export_client.delete(url, headers=HEADERS).status_code == 200
    with Session(lifecycle_engine) as session:
        rows = _outbox(session)
        assert len(rows) == 3
        assert rows[-1].kind == SessionNotificationKind.CANCELLED
        assert "has been cancelled" in rows[-1].body


def test_rollback_removes_event_and_outbox(lifecycle_engine):
    ids = seed_personal_data(lifecycle_engine, owner=True)
    new_id = uuid.uuid4()
    with (
        pytest.raises(RuntimeError, match="synthetic failure"),
        Session(lifecycle_engine) as session,
    ):
        group = session.get(Group, ids["group"])
        event = ConfirmedSession(
            id=new_id,
            group_id=group.id,
            day=date(2026, 10, 7),
            confirmed_by_user_id=ids["user"],
        )
        session.add(event)
        session.flush()
        assert (
            enqueue_session_event_emails(
                session,
                event=event,
                group=group,
                kind=SessionNotificationKind.SCHEDULED,
                actor_user_id=ids["user"],
            )
            == 1
        )
        session.flush()
        raise RuntimeError("synthetic failure")
    with Session(lifecycle_engine) as session:
        assert session.get(ConfirmedSession, new_id) is None
        assert _outbox(session) == []


def test_worker_retry_current_email_and_discard(
    lifecycle_engine, export_client, caplog
):
    ids = seed_personal_data(lifecycle_engine, owner=True)
    assert _create(export_client, ids["group"]).status_code == 200
    with Session(lifecycle_engine) as session:
        row = _outbox(session)[0]
        now = row.next_attempt_at.replace(tzinfo=timezone.utc) + timedelta(seconds=1)
        session.rollback()
        sender = Mock()
        before = session.scalar(
            sa.select(sa.func.count()).select_from(SessionNotificationDelivery)
        )
        assert (
            process_session_event_emails(session, now_utc=now, dry_run=True)["pending"]
            == 1
        )
        assert (
            session.scalar(
                sa.select(sa.func.count()).select_from(SessionNotificationDelivery)
            )
            == before
        )
        sender.send.side_effect = EmailDeliveryError("sanitized")
        failed = process_session_event_emails(
            session, now_utc=now, sender=sender, clock=lambda: now
        )
        assert failed["failed"] == 1
        assert _outbox(session)[0].attempt_count == 1
        assert _outbox(session)[0].next_attempt_at.replace(
            tzinfo=timezone.utc
        ) == now + timedelta(minutes=1)
        assert (
            session.scalar(
                sa.select(sa.func.count()).select_from(SessionNotificationDelivery)
            )
            == before
        )
        session.get(Account, ids["other_account"]).email = "fresh@example.test"
        session.commit()
        sender.send.side_effect = None
        later = now + timedelta(minutes=1)
        assert (
            process_session_event_emails(session, now_utc=later, sender=sender)["sent"]
            == 1
        )
        assert sender.send.call_args.args[0].recipient == "fresh@example.test"
        assert _outbox(session) == []
        assert (
            session.scalar(
                sa.select(sa.func.count()).select_from(SessionNotificationDelivery)
            )
            == before + 1
        )
        assert (
            process_session_event_emails(session, now_utc=later, sender=sender)["sent"]
            == 0
        )
        assert "fresh@example.test" not in caplog.text


def test_worker_keeps_event_order_and_ignores_future_retry(
    lifecycle_engine, export_client
):
    ids = seed_personal_data(lifecycle_engine, owner=True)
    assert _create(export_client, ids["group"]).status_code == 200
    url = f"/api/groups/{ids['group']}/confirmed-sessions/{DAY}"
    assert (
        export_client.patch(
            url, headers=HEADERS, json={"title": "Castle raid"}
        ).status_code
        == 200
    )
    with Session(lifecycle_engine) as session:
        first, second = _outbox(session)
        now = max(first.next_attempt_at, second.next_attempt_at).replace(
            tzinfo=timezone.utc
        ) + timedelta(seconds=1)
        first.next_attempt_at = now + timedelta(minutes=5)
        session.commit()
        sender = Mock()
        result = process_session_event_emails(session, now_utc=now, sender=sender)
        assert result["pending"] == 1
        assert result["blocked_order"] == 1
        sender.send.assert_not_called()
        result = process_session_event_emails(
            session, now_utc=now + timedelta(minutes=5), sender=sender
        )
        assert result["sent"] == 2
        assert "scheduled" in sender.send.call_args_list[0].args[0].subject
        assert "changed" in sender.send.call_args_list[1].args[0].subject


def test_declined_rsvp_does_not_block_event_email(lifecycle_engine, export_client):
    ids = seed_personal_data(lifecycle_engine, owner=True)
    created = _create(export_client, ids["group"])
    assert created.status_code == 200
    with Session(lifecycle_engine) as session:
        row = _outbox(session)[0]
        session.add(
            SessionRsvp(
                session_id=uuid.UUID(created.json()["id"]),
                user_id=ids["other"],
                status=SessionRsvpStatus.DECLINED,
            )
        )
        session.commit()
        sender = Mock()
        now = row.next_attempt_at.replace(tzinfo=timezone.utc) + timedelta(seconds=1)
        assert (
            process_session_event_emails(session, now_utc=now, sender=sender)["sent"]
            == 1
        )
        sender.send.assert_called_once()


@pytest.mark.parametrize("reason", ["disabled", "left", "no_email", "no_account"])
def test_worker_discards_ineligible_recipient(lifecycle_engine, export_client, reason):
    ids = seed_personal_data(lifecycle_engine, owner=True)
    assert _create(export_client, ids["group"]).status_code == 200
    with Session(lifecycle_engine) as session:
        row = _outbox(session)[0]
        now = row.next_attempt_at.replace(tzinfo=timezone.utc) + timedelta(seconds=1)
        other = session.get(User, ids["other"])
        if reason == "disabled":
            other.important_session_emails_enabled = False
        elif reason == "left":
            session.delete(session.get(GroupMembership, (ids["group"], ids["other"])))
        elif reason == "no_email":
            session.get(Account, ids["other_account"]).email = None
        else:
            other.account_id = None
        session.commit()
        sender = Mock()
        assert (
            process_session_event_emails(session, now_utc=now, sender=sender)[
                "discarded"
            ]
            == 1
        )
        sender.send.assert_not_called()
        assert _outbox(session) == []


def test_email_copy_add_remove_and_untimed(lifecycle_engine):
    ids = seed_personal_data(lifecycle_engine, owner=True)
    with Session(lifecycle_engine) as session:
        event = session.get(ConfirmedSession, ids["event"])
        group = session.get(Group, ids["group"])
        before = (event.title, None, None)
        event.start_time = time(20)
        event.duration_minutes = 180
        _, body = event_email_content(
            event, group, SessionNotificationKind.CHANGED, before=before
        )
        assert "Time: Not set -> 20:00" in body
        assert "Duration: Not set -> 180 min" in body
        event.start_time = event.duration_minutes = None
        _, body = event_email_content(
            event,
            group,
            SessionNotificationKind.CHANGED,
            before=(event.title, time(20), 180),
        )
        assert "Time: 20:00 -> Not set" in body
        assert "Duration: 180 min -> Not set" in body
        _, body = event_email_content(event, group, SessionNotificationKind.CANCELLED)
        assert "Time not set" in body
        assert "Shared notes" not in body


def test_preference_partial_patch_validation(lifecycle_engine, export_client):
    ids = seed_personal_data(lifecycle_engine)
    url = "/api/me/notification-preferences"
    assert export_client.get(url, headers=HEADERS).json() == {
        "session_reminder_minutes": 1440,
        "important_session_emails_enabled": True,
    }
    assert export_client.patch(
        url,
        headers=HEADERS,
        json={
            "important_session_emails_enabled": False,
        },
    ).json() == {
        "session_reminder_minutes": 1440,
        "important_session_emails_enabled": False,
    }
    assert export_client.patch(
        url,
        headers=HEADERS,
        json={
            "session_reminder_minutes": None,
        },
    ).json() == {
        "session_reminder_minutes": None,
        "important_session_emails_enabled": False,
    }
    for payload in (
        {},
        {"important_session_emails_enabled": None},
        {"important_session_emails_enabled": "false"},
        {"important_session_emails_enabled": 1},
        {"session_reminder_minutes": 42},
    ):
        assert (
            export_client.patch(url, headers=HEADERS, json=payload).status_code == 422
        )
    with Session(lifecycle_engine) as session:
        assert session.get(User, ids["other"]).important_session_emails_enabled is True


def test_account_export_and_deletion_include_pending_outbox(lifecycle_engine):
    ids = seed_personal_data(lifecycle_engine)
    with Session(lifecycle_engine) as session:
        group = session.get(Group, ids["group"])
        event = session.get(ConfirmedSession, ids["event"])
        # Another member is the actor so the departing user is the recipient.
        assert (
            enqueue_session_event_emails(
                session,
                event=event,
                group=group,
                kind=SessionNotificationKind.SCHEDULED,
                actor_user_id=ids["other"],
            )
            == 1
        )
        session.commit()
    with Session(lifecycle_engine) as session:
        exported = export_account_data(session, session.get(Account, ids["account"]))
        assert exported["schema_version"] == 3
        assert exported["profile"]["important_session_emails_enabled"] is True
        assert len(exported["pending_session_emails"]) == 1
        assert "recipient" not in exported["pending_session_emails"][0]
    with Session(lifecycle_engine) as session:
        summary = delete_account_data(session, ids["account"], apply=True)
        assert summary["pending_session_emails"] == 1
    with Session(lifecycle_engine) as session:
        assert _outbox(session) == []
        assert session.get(User, ids["user"]).important_session_emails_enabled is False
