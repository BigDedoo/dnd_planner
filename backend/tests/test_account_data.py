from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.account_data import AccountDeletionError, delete_account_data
from backend.cli.delete_account_data import main as deletion_main
from backend.config import Settings
from backend.db import DatabaseRuntime
from backend.main import create_app
from backend.models import (
    Account,
    AccountIdentity,
    Availability,
    AvailabilityStatus,
    Base,
    ConfirmedSession,
    Group,
    GroupInvite,
    GroupMembership,
    LegacyProfileRecovery,
    MembershipRole,
    SessionNotificationDelivery,
    SessionNotificationKind,
    SessionRsvp,
    SessionRsvpStatus,
    User,
)
from backend.tests.test_phase_2b_auth import MockRequestAuthenticator


def seed_personal_data(engine, *, owner=False, history=True):
    with Session(engine, expire_on_commit=False) as session:
        account = Account(
            id=uuid.uuid4(),
            email="departing@example.test",
            username="departing",
            display_name="Account name",
            profile_synced_at=datetime.now(timezone.utc),
        )
        other_account = Account(id=uuid.uuid4(), email="private-other@example.test")
        session.add_all([account, other_account])
        session.flush()
        user = User(
            id=uuid.uuid4(),
            account_id=account.id,
            display_name="Personal name",
            email="profile@example.test",
            auth_provider="legacy",
            auth_subject="private-subject",
        )
        other = User(
            id=uuid.uuid4(), account_id=other_account.id, display_name="Other player"
        )
        group = Group(id=uuid.uuid4(), name="Shared campaign")
        session.add_all([user, other, group])
        session.flush()
        event = ConfirmedSession(
            id=uuid.uuid4(),
            group_id=group.id,
            day=date(2026, 10, 5),
            title="Shared session",
            notes="Shared notes",
            confirmed_by_user_id=user.id if history else other.id,
            cancelled_by_user_id=user.id if history else None,
        )
        session.add(event)
        session.flush()
        session.add_all(
            [
                AccountIdentity(
                    account_id=account.id,
                    provider="clerk",
                    provider_subject="subject-own",
                ),
                AccountIdentity(
                    account_id=other_account.id,
                    provider="clerk",
                    provider_subject="subject-other",
                ),
                GroupMembership(
                    group_id=group.id,
                    user_id=user.id,
                    nickname="Scout",
                    role=MembershipRole.OWNER if owner else MembershipRole.MEMBER,
                    display_order=0,
                ),
                GroupMembership(
                    group_id=group.id,
                    user_id=other.id,
                    role=MembershipRole.MEMBER if owner else MembershipRole.OWNER,
                    display_order=1,
                ),
                Availability(
                    user_id=user.id, day=event.day, status=AvailabilityStatus.AVAILABLE
                ),
                Availability(
                    user_id=other.id,
                    day=date(2026, 11, 1),
                    status=AvailabilityStatus.UNAVAILABLE,
                ),
                SessionRsvp(
                    session_id=event.id, user_id=user.id, status=SessionRsvpStatus.GOING
                ),
                SessionRsvp(
                    session_id=event.id,
                    user_id=other.id,
                    status=SessionRsvpStatus.DECLINED,
                ),
                SessionNotificationDelivery(
                    session_id=event.id,
                    recipient_user_id=user.id,
                    kind=SessionNotificationKind.SCHEDULED,
                    dedupe_key="own-notification",
                ),
                SessionNotificationDelivery(
                    session_id=event.id,
                    recipient_user_id=other.id,
                    kind=SessionNotificationKind.SCHEDULED,
                    dedupe_key="other-notification",
                ),
                GroupInvite(
                    group_id=group.id,
                    created_by_user_id=user.id,
                    code_hash="private-hash",
                ),
                LegacyProfileRecovery(
                    user_id=user.id,
                    claimed_by_account_id=account.id,
                    claimed_at=datetime.now(timezone.utc),
                ),
            ]
        )
        session.commit()
        return {
            "account": account.id,
            "user": user.id,
            "other": other.id,
            "other_account": other_account.id,
            "group": group.id,
            "event": event.id,
        }


def snapshot(engine):
    with engine.connect() as connection:
        return {
            table.name: sorted(
                repr(tuple(row)) for row in connection.execute(sa.select(table))
            )
            for table in Base.metadata.sorted_tables
        }


@pytest.fixture
def lifecycle_engine(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'account-data.db'}")

    @sa.event.listens_for(engine, "connect")
    def configure(connection, _):
        connection.create_function(
            "btrim", 1, lambda value: value.strip() if value else value
        )
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


class AccountDeletionCases:
    def test_dry_run_has_no_writes_and_reports_owner(self, lifecycle_engine):
        ids = seed_personal_data(lifecycle_engine, owner=True)
        before = snapshot(lifecycle_engine)
        with Session(lifecycle_engine) as session:
            summary = delete_account_data(session, ids["account"])
        assert summary["applied"] is False
        assert summary["owned_groups"] == 1
        assert (
            summary["availability"]
            == summary["rsvps"]
            == summary["created_invites"]
            == 1
        )
        assert summary["retain_anonymized_user"] is True
        assert "Transfer ownership" in summary["blocker"]
        assert "Personal name" not in json.dumps(summary)
        assert snapshot(lifecycle_engine) == before
        with (
            Session(lifecycle_engine) as session,
            pytest.raises(AccountDeletionError, match="Transfer ownership"),
        ):
            delete_account_data(session, ids["account"], apply=True)
        assert snapshot(lifecycle_engine) == before

    @pytest.mark.parametrize("history", [False, True])
    def test_apply_removes_only_own_data_and_preserves_history(
        self, lifecycle_engine, history
    ):
        ids = seed_personal_data(lifecycle_engine, history=history)
        with Session(lifecycle_engine) as session:
            assert delete_account_data(session, ids["account"], apply=True)["applied"]
        with Session(lifecycle_engine) as session:
            assert session.get(Account, ids["account"]) is None
            assert (
                session.scalar(
                    sa.select(sa.func.count())
                    .select_from(AccountIdentity)
                    .where(AccountIdentity.account_id == ids["account"])
                )
                == 0
            )
            for model, column in [
                (Availability, Availability.user_id),
                (GroupMembership, GroupMembership.user_id),
                (SessionRsvp, SessionRsvp.user_id),
                (
                    SessionNotificationDelivery,
                    SessionNotificationDelivery.recipient_user_id,
                ),
                (GroupInvite, GroupInvite.created_by_user_id),
                (LegacyProfileRecovery, LegacyProfileRecovery.user_id),
            ]:
                assert (
                    session.scalar(
                        sa.select(sa.func.count())
                        .select_from(model)
                        .where(column == ids["user"])
                    )
                    == 0
                )
            user = session.get(User, ids["user"])
            if history:
                assert user.display_name == "Deleted user" and user.timezone == "UTC"
                assert user.session_reminder_minutes is None
                assert (
                    user.account_id
                    is user.email
                    is user.auth_provider
                    is user.auth_subject
                    is None
                )
            else:
                assert user is None
            assert session.get(Group, ids["group"]).name == "Shared campaign"
            assert session.get(ConfirmedSession, ids["event"]).notes == "Shared notes"
            assert (
                session.get(Account, ids["other_account"]).email
                == "private-other@example.test"
            )
            assert (
                session.get(GroupMembership, (ids["group"], ids["other"])).role
                == MembershipRole.OWNER
            )
            assert (
                session.get(Availability, (ids["other"], date(2026, 11, 1))) is not None
            )
            assert (
                session.get(SessionRsvp, (ids["event"], ids["other"])).status
                == SessionRsvpStatus.DECLINED
            )
            assert (
                session.scalar(
                    sa.select(sa.func.count()).select_from(SessionNotificationDelivery)
                )
                == 1
            )
        with (
            Session(lifecycle_engine) as session,
            pytest.raises(AccountDeletionError, match="does not exist"),
        ):
            delete_account_data(session, ids["account"], apply=True)

    def test_unlinked_and_missing_account(self, lifecycle_engine):
        with Session(lifecycle_engine) as session:
            account = Account(id=uuid.uuid4())
            session.add(account)
            session.flush()
            session.add(
                AccountIdentity(
                    account_id=account.id, provider="clerk", provider_subject="unlinked"
                )
            )
            account_id = account.id
            session.commit()
        with Session(lifecycle_engine) as session:
            preview = delete_account_data(session, account_id)
            assert preview["user_id"] is None and preview["identities"] == 1
            assert delete_account_data(session, account_id, apply=True)["applied"]
        with Session(lifecycle_engine) as session:
            assert (
                session.scalar(sa.select(sa.func.count()).select_from(AccountIdentity))
                == 0
            )
            session.rollback()
            with pytest.raises(AccountDeletionError, match="does not exist"):
                delete_account_data(session, uuid.uuid4(), apply=True)

    def test_failure_rolls_back_all_changes(self, lifecycle_engine):
        ids = seed_personal_data(lifecycle_engine)
        before = snapshot(lifecycle_engine)

        def fail_late(_conn, _cursor, statement, _parameters, _context, _many):
            if statement.startswith("DELETE FROM accounts"):
                raise RuntimeError("Simulated failure with SECRET driver details")

        sa.event.listen(lifecycle_engine, "before_cursor_execute", fail_late)
        try:
            with (
                Session(lifecycle_engine) as session,
                pytest.raises(AccountDeletionError, match="rolled back") as error,
            ):
                delete_account_data(session, ids["account"], apply=True)
            assert "SECRET" not in str(error.value)
        finally:
            sa.event.remove(lifecycle_engine, "before_cursor_execute", fail_late)
        assert snapshot(lifecycle_engine) == before

    def test_unexpected_dependency_fails_closed(self, lifecycle_engine):
        ids = seed_personal_data(lifecycle_engine)
        metadata = sa.MetaData()
        sa.Table("accounts", metadata, sa.Column("id", sa.Uuid(), primary_key=True))
        extra = sa.Table(
            "unexpected_account_dependency",
            metadata,
            sa.Column(
                "account_id",
                sa.Uuid(),
                sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            ),
        )
        extra.create(lifecycle_engine)
        try:
            with (
                Session(lifecycle_engine) as session,
                pytest.raises(AccountDeletionError, match="Unexpected"),
            ):
                delete_account_data(session, ids["account"], apply=True)
            with Session(lifecycle_engine) as session:
                assert session.get(Account, ids["account"]) is not None
        finally:
            extra.drop(lifecycle_engine)


class TestSqliteAccountDeletion(AccountDeletionCases):
    pass


@pytest.fixture
def export_client(lifecycle_engine):
    auth = MockRequestAuthenticator()
    auth.add_session(token="private-session-token", subject="subject-own")
    runtime = DatabaseRuntime(lifecycle_engine, "isolated test database")
    app = create_app(
        Settings(_env_file=None, APP_ENV="test", DATABASE_URL=None),
        database_runtime=runtime,
    )
    app.state.request_authenticator = auth
    app.state.clerk_profile_client = auth
    with patch("backend.main.validate_database_readiness"), TestClient(app) as client:
        yield client


@pytest.mark.parametrize("path", ["/me/export", "/api/me/export"])
def test_export_authenticated_and_isolated(lifecycle_engine, export_client, path):
    ids = seed_personal_data(lifecycle_engine)
    assert export_client.get(path).status_code == 401
    before = snapshot(lifecycle_engine)
    response = export_client.get(
        path, headers={"Authorization": "Bearer private-session-token"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="dnd-planner-personal-data.json"'
    )
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["schema_version"] == 3 and data["exported_at"]
    assert data["profile"]["session_reminder_minutes"] == 1440
    assert data["profile"]["important_session_emails_enabled"] is True
    assert data["account"]["id"] == str(ids["account"])
    assert data["account"]["email"] == "departing@example.test"
    assert data["profile"]["display_name"] == "Personal name"
    assert data["memberships"][0]["nickname"] == "Scout"
    assert data["memberships"][0]["group_name"] == "Shared campaign"
    assert (
        len(data["availability"]) == 1
        and data["availability"][0]["status"] == "available"
    )
    assert (
        len(data["rsvps"]) == 1
        and data["rsvps"][0]["session_title"] == "Shared session"
    )
    assert data["rsvps"][0]["status"] == "going"
    assert len(data["notifications"]) == len(data["created_invites"]) == 1
    for forbidden in [
        "private-other",
        "subject-own",
        "subject-other",
        "private-subject",
        "private-hash",
        "private-session-token",
        "DATABASE_URL",
        "auth_subject",
        "code_hash",
        str(ids["other"]),
    ]:
        assert forbidden not in response.text
    assert snapshot(lifecycle_engine) == before


def test_unlinked_export_does_not_require_onboarding(lifecycle_engine, export_client):
    with Session(lifecycle_engine) as session:
        account = Account(id=uuid.uuid4(), profile_synced_at=datetime.now(timezone.utc))
        session.add(account)
        session.flush()
        session.add(
            AccountIdentity(
                account_id=account.id, provider="clerk", provider_subject="subject-own"
            )
        )
        session.commit()
    response = export_client.get(
        "/api/me/export", headers={"Authorization": "Bearer private-session-token"}
    )
    assert response.status_code == 200
    assert response.json()["profile"] is None
    assert response.json()["memberships"] == []


def test_cli_defaults_dry_run_and_requires_explicit_apply(
    lifecycle_engine, monkeypatch, capsys
):
    ids = seed_personal_data(lifecycle_engine)
    runtime = DatabaseRuntime(lifecycle_engine, "isolated test database")
    monkeypatch.setattr(
        "backend.cli.delete_account_data.create_required_database_runtime",
        lambda _: runtime,
    )
    monkeypatch.setattr(
        "backend.cli.delete_account_data.validate_database_readiness", lambda _: None
    )
    assert deletion_main(["--account-id", str(ids["account"])]) == 0
    assert json.loads(capsys.readouterr().out)["applied"] is False
    assert deletion_main(["--account-id", str(ids["account"]), "--apply"]) == 0
    assert json.loads(capsys.readouterr().out)["applied"] is True


def test_cli_invalid_database_is_redacted(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "invalid://SECRET")
    assert deletion_main(["--account-id", str(uuid.uuid4()), "--apply"]) == 1
    output = capsys.readouterr()
    assert "SECRET" not in output.err and "configuration" in output.err
