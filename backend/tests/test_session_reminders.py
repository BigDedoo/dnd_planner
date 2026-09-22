from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.config import Settings
from backend.email_delivery import EmailDeliveryError, ReminderEmail, SmtpReminderSender
from backend.models import (
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
from backend.notifications import process_session_reminders
from backend.tests.test_account_data import (
    export_client,
    lifecycle_engine,
    seed_personal_data,
)

# Reuse the isolated, synthetic SQLite fixture and authenticated client.
__all__ = ["export_client", "lifecycle_engine"]
START = datetime(2026, 8, 29, 18, tzinfo=timezone.utc)
HEADERS = {"Authorization": "Bearer private-session-token"}


def seed_reminder(engine):
    ids = seed_personal_data(engine)
    with Session(engine) as session:
        event = session.get(ConfirmedSession, ids["event"])
        event.day = date(2026, 8, 29)
        event.start_time = time(20)
        event.duration_minutes = 180
        event.cancelled_by_user_id = None
        session.get(Group, ids["group"]).timezone = "Europe/Paris"
        session.get(User, ids["other"]).session_reminder_minutes = None
        session.commit()
    return ids


class ReminderCases:
    @pytest.mark.parametrize("lead", [1440, 180])
    @pytest.mark.parametrize("offset,expected", [(-1, 0), (0, 1), (900, 1)])
    def test_due_and_catch_up(self, lifecycle_engine, lead, offset, expected):
        ids = seed_reminder(lifecycle_engine)
        with Session(lifecycle_engine) as session:
            session.get(User, ids["user"]).session_reminder_minutes = lead
            session.commit()
            sender = Mock()
            result = process_session_reminders(
                session,
                now_utc=START - timedelta(minutes=lead) + timedelta(seconds=offset),
                sender=sender,
            )
            assert result["sent"] == expected
            assert sender.send.call_count == expected
            if expected:
                message = sender.send.call_args.args[0]
                assert message.recipient == "departing@example.test"
                assert "profile@example.test" not in message.body
                assert "Saturday 29 August 2026 at 20:00" in message.body
                assert "Europe/Paris" in message.body
                assert "Duration: 180 minutes" in message.body
                assert f"/groups/{ids['group']}?day=2026-08-29" in message.body
                assert "Shared session" in message.subject

    @pytest.mark.parametrize("offset", [0, 1, 86400])
    def test_never_sends_at_or_after_start(self, lifecycle_engine, offset):
        seed_reminder(lifecycle_engine)
        with Session(lifecycle_engine) as session:
            sender = Mock()
            assert (
                process_session_reminders(
                    session, now_utc=START + timedelta(seconds=offset), sender=sender
                )["sent"]
                == 0
            )
            sender.send.assert_not_called()

    @pytest.mark.parametrize(
        "reason",
        [
            "off",
            "declined",
            "cancelled",
            "untimed",
            "no_email",
            "bad_email",
            "no_account",
            "left",
        ],
    )
    def test_ineligible_recipient(self, lifecycle_engine, reason):
        ids = seed_reminder(lifecycle_engine)
        with Session(lifecycle_engine) as session:
            user = session.get(User, ids["user"])
            event = session.get(ConfirmedSession, ids["event"])
            if reason == "off":
                user.session_reminder_minutes = None
            elif reason == "declined":
                session.scalar(
                    sa.select(SessionRsvp).where(SessionRsvp.user_id == user.id)
                ).status = SessionRsvpStatus.DECLINED
            elif reason == "cancelled":
                event.cancelled_at = START - timedelta(days=2)
            elif reason == "untimed":
                event.start_time = event.duration_minutes = None
            elif reason in {"no_email", "bad_email"}:
                session.get(Account, ids["account"]).email = (
                    None if reason == "no_email" else "not-an-address"
                )
            elif reason == "no_account":
                user.account_id = None
            elif reason == "left":
                session.execute(
                    sa.delete(GroupMembership).where(GroupMembership.user_id == user.id)
                )
            session.commit()
            sender = Mock()
            assert (
                process_session_reminders(
                    session, now_utc=START - timedelta(hours=1), sender=sender
                )["sent"]
                == 0
            )
            sender.send.assert_not_called()

    @pytest.mark.parametrize("rsvp", ["going", "maybe", None])
    def test_non_declined_rsvp_eligible(self, lifecycle_engine, rsvp):
        ids = seed_reminder(lifecycle_engine)
        with Session(lifecycle_engine) as session:
            row = session.scalar(
                sa.select(SessionRsvp).where(SessionRsvp.user_id == ids["user"])
            )
            if rsvp is None:
                session.delete(row)
            else:
                row.status = SessionRsvpStatus(rsvp)
            session.commit()
            assert (
                process_session_reminders(
                    session, now_utc=START - timedelta(hours=1), sender=Mock()
                )["sent"]
                == 1
            )

    def test_durable_dedupe_preference_and_reschedule(self, lifecycle_engine):
        ids = seed_reminder(lifecycle_engine)
        with Session(lifecycle_engine) as session:
            sender = Mock()

            def run(now):
                session.commit()
                return process_session_reminders(session, now_utc=now, sender=sender)[
                    "sent"
                ]

            assert run(START - timedelta(days=1)) == 1
            assert run(START - timedelta(hours=23)) == 0
            session.get(ConfirmedSession, ids["event"]).title = "New title"
            session.get(ConfirmedSession, ids["event"]).notes = "New notes"
            assert run(START - timedelta(hours=22)) == 0
            session.get(User, ids["user"]).session_reminder_minutes = None
            assert run(START - timedelta(hours=4)) == 0
            session.get(User, ids["user"]).session_reminder_minutes = 1440
            assert run(START - timedelta(hours=4)) == 0
            session.get(User, ids["user"]).session_reminder_minutes = 180
            assert run(START - timedelta(hours=3)) == 1
            session.get(ConfirmedSession, ids["event"]).start_time = time(21)
            assert run(START - timedelta(hours=2)) == 1
            rows = session.scalars(
                sa.select(SessionNotificationDelivery).where(
                    SessionNotificationDelivery.kind
                    == SessionNotificationKind.UPCOMING_REMINDER
                )
            ).all()
            assert len(rows) == len({row.dedupe_key for row in rows}) == 3
            assert sender.send.call_count == 3

    def test_failure_retries_and_dry_run_writes_nothing(self, lifecycle_engine):
        seed_reminder(lifecycle_engine)
        with Session(lifecycle_engine) as session:
            before = session.scalar(
                sa.select(sa.func.count()).select_from(SessionNotificationDelivery)
            )
            sender = Mock()
            due = START - timedelta(hours=1)
            assert (
                process_session_reminders(
                    session, now_utc=due, dry_run=True, sender=sender
                )["due"]
                == 1
            )
            sender.send.assert_not_called()
            sender.send.side_effect = EmailDeliveryError("SMTP delivery failed")
            assert (
                process_session_reminders(session, now_utc=due, sender=sender)["failed"]
                == 1
            )
            assert (
                session.scalar(
                    sa.select(sa.func.count()).select_from(SessionNotificationDelivery)
                )
                == before
            )
            sender.send.side_effect = None
            assert (
                process_session_reminders(session, now_utc=due, sender=sender)["sent"]
                == 1
            )
            assert (
                session.scalar(
                    sa.select(sa.func.count()).select_from(SessionNotificationDelivery)
                )
                == before + 1
            )
            assert (
                process_session_reminders(session, now_utc=due, sender=sender)["sent"]
                == 0
            )

    @pytest.mark.parametrize(
        "day,hour", [(date(2026, 8, 29), 18), (date(2026, 12, 12), 19)]
    )
    def test_paris_seasons_use_canonical_utc(self, lifecycle_engine, day, hour):
        ids = seed_reminder(lifecycle_engine)
        with Session(lifecycle_engine) as session:
            session.get(ConfirmedSession, ids["event"]).day = day
            session.commit()
            due = datetime.combine(day, time(hour), tzinfo=timezone.utc) - timedelta(
                days=1
            )
            assert (
                process_session_reminders(
                    session, now_utc=due - timedelta(seconds=1), dry_run=True
                )["due"]
                == 0
            )
            assert (
                process_session_reminders(session, now_utc=due, dry_run=True)["due"]
                == 1
            )

    def test_bounded_scan_invalid_time_and_late_worker(self, lifecycle_engine):
        ids = seed_reminder(lifecycle_engine)
        with Session(lifecycle_engine) as session:
            assert (
                process_session_reminders(
                    session, now_utc=START - timedelta(days=8), dry_run=True
                )["due"]
                == 0
            )
            assert (
                process_session_reminders(
                    session,
                    now_utc=START - timedelta(hours=1),
                    sender=Mock(),
                    clock=lambda: START,
                )["sent"]
                == 0
            )
            event = session.get(ConfirmedSession, ids["event"])
            event.day, event.start_time = date(2026, 3, 29), time(2, 30)
            session.commit()
            result = process_session_reminders(
                session,
                now_utc=datetime(2026, 3, 28, tzinfo=timezone.utc),
                dry_run=True,
            )
            assert result["skipped_invalid_time"] == 1
            assert result["due"] == 0


class TestSqliteReminders(ReminderCases):
    pass


@pytest.mark.parametrize(
    "path", ["/me/notification-preferences", "/api/me/notification-preferences"]
)
def test_preferences_are_own_linked_user_only(lifecycle_engine, export_client, path):
    ids = seed_personal_data(lifecycle_engine)
    assert export_client.get(path).status_code == 401
    assert (
        export_client.patch(path, json={"session_reminder_minutes": None}).status_code
        == 401
    )
    assert export_client.get(path, headers=HEADERS).json() == {
        "session_reminder_minutes": 1440
    }
    for value in [60, 180, 720, 1440, 4320, 10080, None]:
        response = export_client.patch(
            path, headers=HEADERS, json={"session_reminder_minutes": value}
        )
        assert response.status_code == 200
        assert response.json() == {"session_reminder_minutes": value}
        assert export_client.get(path, headers=HEADERS).json() == response.json()
    for value in [-1, 0, 42, 10081, True, "180", 180.5]:
        assert (
            export_client.patch(
                path, headers=HEADERS, json={"session_reminder_minutes": value}
            ).status_code
            == 422
        )
    assert (
        export_client.patch(
            path,
            headers=HEADERS,
            json={"user_id": str(ids["other"]), "session_reminder_minutes": 60},
        ).status_code
        == 422
    )
    with Session(lifecycle_engine) as session:
        assert session.get(User, ids["other"]).session_reminder_minutes == 1440
    export_client.app.state.settings.mutations_enabled = False
    assert (
        export_client.patch(
            path, headers=HEADERS, json={"session_reminder_minutes": 60}
        ).status_code
        == 503
    )
    assert export_client.get(path, headers=HEADERS).status_code == 200
    with Session(lifecycle_engine) as session:
        session.get(User, ids["user"]).account_id = None
        session.commit()
    assert export_client.get(path, headers=HEADERS).status_code == 403


def mail_settings(**overrides):
    values = dict(
        EMAIL_DELIVERY_ENABLED=True,
        SMTP_HOST="smtp.example.test",
        SMTP_USERNAME="support@example.test",
        SMTP_PASSWORD="synthetic-password",
        SMTP_FROM_EMAIL="support@example.test",
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_smtp_tls_auth_single_recipient_and_headers(monkeypatch):
    smtp = Mock()
    smtp.return_value.send_message.return_value = {}
    monkeypatch.setattr("backend.email_delivery.smtplib.SMTP", smtp)
    settings = mail_settings()
    message = ReminderEmail(
        "recipient@example.test", "Session reminder", "Local session details"
    )
    SmtpReminderSender(settings).send(message)
    smtp.assert_called_once_with("smtp.example.test", 587, timeout=15)
    tls = smtp.return_value.starttls.call_args.kwargs["context"]
    assert tls.check_hostname and tls.verify_mode.name == "CERT_REQUIRED"
    smtp.return_value.login.assert_called_once_with(
        "support@example.test", "synthetic-password"
    )
    call = smtp.return_value.send_message.call_args
    assert call.kwargs["to_addrs"] == ["recipient@example.test"]
    assert call.kwargs["from_addr"] == "support@example.test"
    email = call.args[0]
    assert str(email["From"]) == "DnD Planner <support@example.test>"
    assert str(email["Reply-To"]) == "support@example.test"
    assert email["Subject"] == "Session reminder"
    assert email.get_content().strip() == "Local session details"
    assert "synthetic-password" not in repr(settings)
    assert "recipient@example.test" not in repr(message)


@pytest.mark.parametrize("phase", ["login", "send_message"])
def test_smtp_failure_is_redacted(monkeypatch, caplog, phase):
    smtp = Mock()
    getattr(smtp.return_value, phase).side_effect = RuntimeError(
        "synthetic-password recipient@example.test"
    )
    monkeypatch.setattr("backend.email_delivery.smtplib.SMTP", smtp)
    with pytest.raises(EmailDeliveryError) as error:
        SmtpReminderSender(mail_settings()).send(
            ReminderEmail("recipient@example.test", "Subject", "Body")
        )
    assert str(error.value) == "SMTP delivery failed"
    assert error.value.__suppress_context__
    assert "synthetic-password" not in caplog.text
    assert "recipient@example.test" not in caplog.text


@pytest.mark.parametrize(
    "invalid",
    [
        {"SMTP_PASSWORD": None},
        {"SMTP_HOST": "bad host"},
        {"SMTP_PORT": 0},
        {"SMTP_STARTTLS": False},
        {"SMTP_USERNAME": ""},
        {"SMTP_FROM_EMAIL": "invalid"},
        {"SMTP_FROM_NAME": "bad\nname"},
    ],
)
def test_enabled_smtp_configuration_fails_closed(invalid):
    with pytest.raises(ValidationError) as error:
        mail_settings(**invalid)
    assert "synthetic-password" not in str(error.value)


def test_cli_disabled_and_failures_are_safe(monkeypatch, capsys):
    from backend.cli import process_session_reminders as cli

    monkeypatch.setattr(
        cli, "Settings", lambda: Settings(_env_file=None, EMAIL_DELIVERY_ENABLED=False)
    )
    assert cli.main([]) == 0
    assert "sent=0" in capsys.readouterr().out
    monkeypatch.setattr(cli, "Settings", lambda: mail_settings())
    monkeypatch.setattr(
        cli.SmtpReminderSender,
        "check_connection",
        Mock(side_effect=RuntimeError("private-credential")),
    )
    assert cli.main(["--check-smtp"]) == 1
    assert "private-credential" not in capsys.readouterr().err
