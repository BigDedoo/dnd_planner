from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from backend.auth import ClerkAuthenticationError, VerifiedClerkSession
from backend.clerk_profile import ClerkProfile
from backend.config import Settings
from backend.db import DatabaseRuntime
from backend.legacy_profile_recovery import claim_legacy_profile
from backend.main import create_app
from backend.models import (
    Account,
    AccountIdentity,
    Availability,
    AvailabilityStatus,
    Base,
    Group,
    GroupMembership,
    LegacyProfileRecovery,
    MembershipRole,
    User,
)


class RecoveryAuthenticator:
    def __init__(self) -> None:
        self.sessions: dict[str, VerifiedClerkSession] = {}
        self.profiles: dict[str, ClerkProfile] = {}

    def add(self, token: str, subject: str, username: str) -> None:
        self.sessions[token] = VerifiedClerkSession(subject=subject)
        self.profiles[subject] = ClerkProfile(
            email=None,
            username=username,
            display_name=username,
        )

    def authenticate(
        self,
        request: Request,
        app_settings: Settings,
    ) -> VerifiedClerkSession:
        del app_settings
        token = request.headers["Authorization"].split()[1]
        try:
            return self.sessions[token]
        except KeyError as exc:
            raise ClerkAuthenticationError("request_rejected") from exc

    def fetch_profile(self, clerk_user_id: str) -> ClerkProfile:
        return self.profiles[clerk_user_id]


@pytest.fixture
def recovery_runtime(tmp_path: Path) -> Iterator[DatabaseRuntime]:
    database_path = tmp_path / "legacy_recovery.db"
    engine = create_engine(f"sqlite:///{database_path}")

    @sa.event.listens_for(engine, "connect")
    def _register_sqlite_functions(dbapi_connection, _):
        dbapi_connection.create_function(
            "btrim", 1, lambda value: value.strip() if value is not None else None
        )

    Base.metadata.create_all(engine)
    runtime = DatabaseRuntime(engine=engine, safe_url=f"sqlite:///{database_path}")
    yield runtime
    runtime.dispose()


@pytest.fixture
def recovery_authenticator() -> RecoveryAuthenticator:
    return RecoveryAuthenticator()


@pytest.fixture
def recovery_app(
    recovery_runtime: DatabaseRuntime,
    recovery_authenticator: RecoveryAuthenticator,
) -> FastAPI:
    app_settings = Settings(
        _env_file=None,
        APP_ENV="test",
        LOG_LEVEL="CRITICAL",
        CORS_ALLOWED_ORIGINS=["http://testserver"],
        LEGACY_PROFILE_RECOVERY_ENABLED=True,
    )
    application = create_app(app_settings, database_runtime=recovery_runtime)
    with patch("backend.main.validate_database_readiness"):
        application.state.request_authenticator = recovery_authenticator
        application.state.clerk_profile_client = recovery_authenticator
        yield application


@pytest.fixture
def recovery_client(recovery_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(recovery_app) as client:
        yield client


def _register_account(
    client: TestClient,
    authenticator: RecoveryAuthenticator,
    label: str,
) -> tuple[uuid.UUID, dict[str, str]]:
    token = f"{label}-token"
    authenticator.add(token, f"{label}-subject", f"{label}-username")
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/api/me", headers=headers)
    assert response.status_code == 200
    return uuid.UUID(response.json()["id"]), headers


def test_recovery_disabled_and_normal_onboarding_unchanged(
    recovery_app: FastAPI,
    recovery_client: TestClient,
    recovery_authenticator: RecoveryAuthenticator,
    recovery_runtime: DatabaseRuntime,
) -> None:
    assert (
        Settings(
            _env_file=None,
            APP_ENV="test",
            CORS_ALLOWED_ORIGINS=["http://testserver"],
        ).legacy_profile_recovery_enabled
        is False
    )
    account_id, headers = _register_account(
        recovery_client, recovery_authenticator, "disabled"
    )
    recovery_app.state.settings.legacy_profile_recovery_enabled = False

    assert (
        recovery_client.get(
            "/api/onboarding/recovery-profiles", headers=headers
        ).status_code
        == 404
    )
    assert (
        recovery_client.post(
            "/api/onboarding/recover",
            headers=headers,
            json={"user_id": str(uuid.uuid4())},
        ).status_code
        == 404
    )
    created = recovery_client.post(
        "/api/onboarding",
        headers=headers,
        json={"display_name": "New player"},
    )
    assert created.status_code == 201
    with recovery_runtime.open_session() as session:
        user = session.scalar(sa.select(User).where(User.account_id == account_id))
        assert user is not None
        assert user.display_name == "New player"


def test_available_profiles_are_explicit_minimal_sorted_and_unclaimed(
    recovery_client: TestClient,
    recovery_authenticator: RecoveryAuthenticator,
    recovery_runtime: DatabaseRuntime,
) -> None:
    _, headers = _register_account(recovery_client, recovery_authenticator, "viewer")
    with recovery_runtime.open_session() as session:
        first = User(display_name="Arnaud")
        second = User(display_name="Daerrus")
        ineligible = User(display_name="Not eligible")
        claimed = User(display_name="Already claimed")
        claimant = Account(display_name="Previous claimant")
        groups = [Group(name="Green Flag"), Group(name="Underdark")]
        session.add_all([first, second, ineligible, claimed, claimant, *groups])
        session.flush()
        session.add_all(
            [
                GroupMembership(
                    group_id=groups[1].id,
                    user_id=first.id,
                    role=MembershipRole.MEMBER,
                    display_order=0,
                ),
                GroupMembership(
                    group_id=groups[0].id,
                    user_id=first.id,
                    role=MembershipRole.MEMBER,
                    display_order=0,
                ),
                LegacyProfileRecovery(user_id=first.id),
                LegacyProfileRecovery(user_id=second.id),
                LegacyProfileRecovery(
                    user_id=claimed.id,
                    claimed_at=sa.func.now(),
                    claimed_by_account_id=claimant.id,
                ),
            ]
        )
        session.commit()
        first_id = first.id
        second_id = second.id

    response = recovery_client.get("/api/onboarding/recovery-profiles", headers=headers)
    assert response.status_code == 200
    assert response.json() == [
        {
            "user_id": str(first_id),
            "display_name": "Arnaud",
            "group_names": ["Green Flag", "Underdark"],
        },
        {
            "user_id": str(second_id),
            "display_name": "Daerrus",
            "group_names": [],
        },
    ]
    assert set(response.json()[0]) == {"user_id", "display_name", "group_names"}


def test_linked_account_cannot_browse_or_claim(
    recovery_client: TestClient,
    recovery_authenticator: RecoveryAuthenticator,
    recovery_runtime: DatabaseRuntime,
) -> None:
    account_id, headers = _register_account(
        recovery_client, recovery_authenticator, "linked"
    )
    with recovery_runtime.open_session() as session:
        linked = User(account_id=account_id, display_name="Linked")
        target = User(display_name="Target")
        session.add_all([linked, target])
        session.flush()
        session.add(LegacyProfileRecovery(user_id=target.id))
        session.commit()
        target_id = target.id

    assert (
        recovery_client.get(
            "/api/onboarding/recovery-profiles", headers=headers
        ).status_code
        == 409
    )
    assert (
        recovery_client.post(
            "/api/onboarding/recover",
            headers=headers,
            json={"user_id": str(target_id)},
        ).status_code
        == 409
    )


def test_claim_reassigns_same_user_preserves_data_and_is_idempotent(
    recovery_client: TestClient,
    recovery_authenticator: RecoveryAuthenticator,
    recovery_runtime: DatabaseRuntime,
) -> None:
    new_account_id, headers = _register_account(
        recovery_client, recovery_authenticator, "new-account"
    )
    second_account_id, second_headers = _register_account(
        recovery_client, recovery_authenticator, "second-account"
    )
    with recovery_runtime.open_session() as session:
        old_account = Account(display_name="Old development account")
        session.add(old_account)
        session.flush()
        old_identity = AccountIdentity(
            account_id=old_account.id,
            provider="clerk",
            provider_subject="old-development-subject",
        )
        legacy_user = User(
            account_id=old_account.id,
            display_name="Legacy hero",
        )
        group = Group(name="Existing campaign")
        session.add_all([old_identity, legacy_user, group])
        session.flush()
        session.add_all(
            [
                GroupMembership(
                    group_id=group.id,
                    user_id=legacy_user.id,
                    role=MembershipRole.OWNER,
                    display_order=0,
                ),
                Availability(
                    user_id=legacy_user.id,
                    day=date(2026, 9, 12),
                    status=AvailabilityStatus.AVAILABLE,
                ),
                LegacyProfileRecovery(user_id=legacy_user.id),
            ]
        )
        session.commit()
        user_id = legacy_user.id
        old_account_id = old_account.id
        old_identity_id = old_identity.id
        group_id = group.id

    first = recovery_client.post(
        "/api/onboarding/recover",
        headers=headers,
        json={"user_id": str(user_id)},
    )
    assert first.status_code == 200
    assert first.json()["user_id"] == str(user_id)
    repeated = recovery_client.post(
        "/api/onboarding/recover",
        headers=headers,
        json={"user_id": str(user_id)},
    )
    assert repeated.status_code == 200
    assert repeated.json()["user_id"] == str(user_id)
    assert (
        recovery_client.post(
            "/api/onboarding/recover",
            headers=second_headers,
            json={"user_id": str(user_id)},
        ).status_code
        == 409
    )

    with recovery_runtime.open_session() as session:
        user = session.get(User, user_id)
        recovery = session.get(LegacyProfileRecovery, user_id)
        assert user is not None and user.id == user_id
        assert user.account_id == new_account_id
        assert recovery is not None
        assert recovery.claimed_at is not None
        assert recovery.claimed_by_account_id == new_account_id
        assert session.get(Account, old_account_id) is not None
        assert session.get(AccountIdentity, old_identity_id) is not None
        assert session.get(Account, second_account_id) is not None
        assert session.get(GroupMembership, (group_id, user_id)) is not None
        assert session.get(Availability, (user_id, date(2026, 9, 12))) is not None


def test_claim_rolls_back_user_and_recovery_together(
    recovery_runtime: DatabaseRuntime,
) -> None:
    with recovery_runtime.open_session() as session:
        account = Account(display_name="New account")
        old_account = Account(display_name="Old account")
        user = User(account=old_account, display_name="Rollback hero")
        session.add_all([account, old_account, user])
        session.flush()
        session.add(LegacyProfileRecovery(user_id=user.id))
        session.commit()
        account_id = account.id
        old_account_id = old_account.id
        user_id = user.id

    with recovery_runtime.open_session() as session:

        def fail_flush(current_session, flush_context, instances):
            del current_session, flush_context, instances
            raise RuntimeError("synthetic mid-transaction failure")

        sa.event.listen(session, "before_flush", fail_flush, once=True)
        with pytest.raises(RuntimeError, match="synthetic mid-transaction failure"):
            claim_legacy_profile(session, account_id, user_id)

    with recovery_runtime.open_session() as session:
        user = session.get(User, user_id)
        recovery = session.get(LegacyProfileRecovery, user_id)
        assert user is not None and user.account_id == old_account_id
        assert recovery is not None
        assert recovery.claimed_at is None
        assert recovery.claimed_by_account_id is None
