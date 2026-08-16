from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from clerk_backend_api.security.types import (
    AuthenticateRequestOptions,
    AuthStatus,
    RequestState,
)
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from backend.auth import (
    CLERK_PROVIDER,
    ClerkAuthenticationError,
    ClerkSDKRequestAuthenticator,
    VerifiedClerkSession,
    resolve_or_provision_account,
)
from backend.config import Settings
from backend.db import DatabaseRuntime
from backend.main import create_app
from backend.models import (
    Account,
    AccountIdentity,
    Base,
    Group,
    GroupMembership,
    MembershipRole,
    User,
)


class MockRequestAuthenticator:
    def __init__(self) -> None:
        self.valid_sessions: dict[str, VerifiedClerkSession] = {}
        self.rejected_tokens: dict[str, str] = {}
        self.unexpected_tokens: set[str] = set()

    def add_session(
        self,
        token: str,
        subject: str,
        email: str | None = None,
        display_name: str | None = None,
    ) -> None:
        self.valid_sessions[token] = VerifiedClerkSession(
            subject=subject,
            email=email,
            display_name=display_name,
        )

    def reject(self, token: str, category: str) -> None:
        self.rejected_tokens[token] = category

    def authenticate(
        self,
        request: Request,
        app_settings: Settings,
    ) -> VerifiedClerkSession:
        del app_settings
        token = request.headers["Authorization"].split()[1]
        if token in self.unexpected_tokens:
            raise RuntimeError("simulated SDK failure")
        if token in self.rejected_tokens:
            raise ClerkAuthenticationError(self.rejected_tokens[token])
        try:
            return self.valid_sessions[token]
        except KeyError as exc:
            raise ClerkAuthenticationError("request_rejected") from exc


@pytest.fixture
def mock_authenticator() -> MockRequestAuthenticator:
    return MockRequestAuthenticator()


@pytest.fixture
def auth_sqlite_runtime(tmp_path: Path) -> Iterator[DatabaseRuntime]:
    db_file = tmp_path / "auth_test.db"
    engine = create_engine(f"sqlite:///{db_file}")

    @sa.event.listens_for(engine, "connect")
    def _register_sqlite_functions(dbapi_connection, _):
        dbapi_connection.create_function(
            "btrim", 1, lambda s: s.strip() if s is not None else None
        )

    Base.metadata.create_all(engine)
    runtime = DatabaseRuntime(engine=engine, safe_url=f"sqlite:///{db_file}")
    yield runtime
    runtime.dispose()


@pytest.fixture
def auth_app(
    auth_sqlite_runtime: DatabaseRuntime,
    mock_authenticator: MockRequestAuthenticator,
) -> FastAPI:
    test_settings = Settings(
        _env_file=None,
        APP_ENV="test",
        LOG_LEVEL="CRITICAL",
        CORS_ALLOWED_ORIGINS=["http://testserver"],
    )
    application = create_app(test_settings, database_runtime=auth_sqlite_runtime)

    with (
        patch("backend.main.validate_database_readiness"),
        patch("backend.main.compatibility.validate_compatibility_dataset"),
    ):
        application.state.request_authenticator = mock_authenticator
        yield application


@pytest.fixture
def client(auth_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(auth_app) as test_client:
        yield test_client


def _authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_unauthenticated_me_returns_401(client: TestClient) -> None:
    response = client.get("/api/me")
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing Authorization header"


def test_invalid_auth_header_format_returns_401(client: TestClient) -> None:
    response = client.get("/api/me", headers={"Authorization": "InvalidToken"})
    assert response.status_code == 401
    assert "Expected 'Bearer <token>'" in response.json()["detail"]


@pytest.mark.parametrize(
    "token",
    [
        "bad-token",
        "eyJhbGciOiJub25lIn0.eyJzdWIiOiJmb3JnZWQifQ.",
        "forged.header.signature",
    ],
)
def test_malformed_unsigned_and_forged_tokens_return_401_without_provisioning(
    client: TestClient,
    auth_sqlite_runtime: DatabaseRuntime,
    token: str,
) -> None:
    response = client.get("/api/me", headers=_authorization(token))
    assert response.status_code == 401
    assert response.json()["detail"] == "Could not validate credentials"

    with auth_sqlite_runtime.open_session() as session:
        assert session.query(Account).count() == 0
        assert session.query(AccountIdentity).count() == 0


def test_authentication_sdk_failure_returns_401(
    client: TestClient,
    mock_authenticator: MockRequestAuthenticator,
) -> None:
    token = "sdk-failure"
    mock_authenticator.unexpected_tokens.add(token)
    assert client.get("/api/me", headers=_authorization(token)).status_code == 401


@pytest.mark.parametrize(
    ("token", "category"),
    [
        ("wrong-authorized-party", "request_rejected_wrong_authorized_party"),
        ("oauth-token", "request_rejected_non_session_token"),
        ("expired-session", "request_rejected_expired_token"),
        ("invalid-signature", "request_rejected_invalid_signature"),
    ],
)
def test_clerk_rejected_authentication_states_return_401(
    client: TestClient,
    mock_authenticator: MockRequestAuthenticator,
    token: str,
    category: str,
) -> None:
    mock_authenticator.reject(token, category)
    assert client.get("/api/me", headers=_authorization(token)).status_code == 401


def test_official_clerk_authenticator_enforces_session_only_and_authorized_parties() -> (
    None
):
    captured: dict[str, Any] = {}

    def fake_authenticate_request(
        request: Request,
        options: AuthenticateRequestOptions,
    ) -> RequestState:
        captured["request"] = request
        captured["options"] = options
        return RequestState(
            status=AuthStatus.SIGNED_IN,
            token="verified-session-token",
            payload={"sub": "user_verified", "email": "verified@example.com"},
        )

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/me",
            "headers": [(b"authorization", b"Bearer verified-session-token")],
        }
    )
    app_settings = Settings(
        _env_file=None,
        CLERK_SECRET_KEY="sk_test_not_a_real_secret",
        CLERK_AUTHORIZED_PARTIES=["https://planner.example"],
    )

    verified = ClerkSDKRequestAuthenticator(fake_authenticate_request).authenticate(
        request,
        app_settings,
    )

    assert verified.subject == "user_verified"
    options = captured["options"]
    assert options.accepts_token == ["session_token"]
    assert options.authorized_parties == ["https://planner.example"]
    assert options.secret_key == "sk_test_not_a_real_secret"


@pytest.mark.parametrize(
    "state",
    [
        RequestState(status=AuthStatus.SIGNED_OUT),
        RequestState(status=AuthStatus.SIGNED_IN, token="token", payload=None),
    ],
)
def test_official_clerk_authenticator_rejects_invalid_sdk_state(
    state: RequestState,
) -> None:
    request = Request({"type": "http", "headers": []})
    app_settings = Settings(
        _env_file=None,
        CLERK_SECRET_KEY="sk_test_not_a_real_secret",
        CLERK_AUTHORIZED_PARTIES=["https://planner.example"],
    )
    authenticator = ClerkSDKRequestAuthenticator(lambda request, options: state)
    with pytest.raises(ClerkAuthenticationError, match="authentication failed"):
        authenticator.authenticate(request, app_settings)


def test_official_clerk_authenticator_fails_closed_without_configuration() -> None:
    request = Request({"type": "http", "headers": []})
    authenticator = ClerkSDKRequestAuthenticator(
        lambda request, options: pytest.fail("SDK must not be called")
    )

    with pytest.raises(ClerkAuthenticationError):
        authenticator.authenticate(request, Settings(_env_file=None))
    with pytest.raises(ClerkAuthenticationError):
        authenticator.authenticate(
            request,
            Settings(
                _env_file=None,
                CLERK_SECRET_KEY="sk_test_not_a_real_secret",
                CLERK_AUTHORIZED_PARTIES=[],
            ),
        )


@pytest.mark.parametrize(
    ("configuration", "expected_error"),
    [
        (
            {"CLERK_AUTHORIZED_PARTIES": ["https://planner.example"]},
            "CLERK_SECRET_KEY is required in production",
        ),
        (
            {"CLERK_SECRET_KEY": "sk_test_not_a_real_secret"},
            "CLERK_AUTHORIZED_PARTIES is required in production",
        ),
    ],
)
def test_production_settings_require_complete_clerk_configuration(
    auth_sqlite_runtime: DatabaseRuntime,
    configuration: dict[str, Any],
    expected_error: str,
) -> None:
    app_settings = Settings(
        _env_file=None,
        APP_ENV="production",
        **configuration,
    )
    application = create_app(app_settings, database_runtime=auth_sqlite_runtime)

    with pytest.raises(ValueError, match=expected_error):
        with TestClient(application):
            pass


def test_verified_session_provisions_only_internal_account_and_identity(
    client: TestClient,
    mock_authenticator: MockRequestAuthenticator,
    auth_sqlite_runtime: DatabaseRuntime,
) -> None:
    token = "valid-token-user-1"
    subject = "user_clerk_12345"
    mock_authenticator.add_session(
        token=token,
        subject=subject,
        email="test@example.com",
        display_name="Test Adventurer",
    )

    response = client.get("/api/me", headers=_authorization(token))
    assert response.status_code == 200
    account_id = uuid.UUID(response.json()["id"])
    assert str(account_id) != subject

    with auth_sqlite_runtime.open_session() as session:
        account = session.get(Account, account_id)
        assert account is not None
        assert account.email == "test@example.com"
        assert len(account.identities) == 1
        assert account.identities[0].provider == CLERK_PROVIDER
        assert account.identities[0].provider_subject == subject
        assert session.query(User).count() == 0


def test_repeated_verified_identity_returns_same_account_without_duplicates(
    client: TestClient,
    mock_authenticator: MockRequestAuthenticator,
    auth_sqlite_runtime: DatabaseRuntime,
) -> None:
    token = "valid-token-repeated"
    mock_authenticator.add_session(token, "user_clerk_repeated")

    first = client.get("/api/me", headers=_authorization(token))
    second = client.get("/api/me", headers=_authorization(token))
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    with auth_sqlite_runtime.open_session() as session:
        assert session.query(Account).count() == 1
        assert session.query(AccountIdentity).count() == 1


def test_unlinked_authenticated_account_is_forbidden_without_creating_user(
    client: TestClient,
    mock_authenticator: MockRequestAuthenticator,
    auth_sqlite_runtime: DatabaseRuntime,
) -> None:
    token = "unlinked-account"
    mock_authenticator.add_session(token, "user_unlinked")

    response = client.get("/api/me/groups", headers=_authorization(token))
    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Authenticated account is not linked to a DnD user"
    )
    with auth_sqlite_runtime.open_session() as session:
        assert session.query(Account).count() == 1
        assert session.query(User).count() == 0


def test_linked_authenticated_account_resolves_existing_dnd_user(
    client: TestClient,
    mock_authenticator: MockRequestAuthenticator,
    auth_sqlite_runtime: DatabaseRuntime,
) -> None:
    token = "linked-account"
    mock_authenticator.add_session(token, "user_linked")
    account_response = client.get("/api/me", headers=_authorization(token))
    account_id = uuid.UUID(account_response.json()["id"])

    with auth_sqlite_runtime.open_session() as session:
        linked_user = User(
            id=uuid.uuid4(),
            account_id=account_id,
            display_name="Linked Legacy User",
            timezone="UTC",
        )
        session.add(linked_user)
        session.commit()

    response = client.get("/api/me/groups", headers=_authorization(token))
    assert response.status_code == 200
    assert response.json() == []
    with auth_sqlite_runtime.open_session() as session:
        assert session.query(User).count() == 1


def test_legacy_users_and_groups_are_isolated_from_accounts(
    auth_sqlite_runtime: DatabaseRuntime,
) -> None:
    with auth_sqlite_runtime.open_session() as session:
        legacy_user_id = uuid.uuid4()
        legacy_user = User(
            id=legacy_user_id,
            display_name="Legacy Aragon",
            timezone="UTC",
        )
        group = Group(id=uuid.uuid4(), name="Fellowship", timezone="UTC")
        membership = GroupMembership(
            group_id=group.id,
            user_id=legacy_user.id,
            role=MembershipRole.OWNER,
            display_order=0,
        )
        session.add_all([legacy_user, group, membership])
        session.commit()

        clerk_account = resolve_or_provision_account(
            session=session,
            provider="clerk",
            provider_subject="user_fellowship_clerk",
            email="clerk@fellowship.org",
            display_name="Clerk Aragon",
        )

        assert clerk_account.id != legacy_user_id
        assert session.query(User).count() == 1
        assert session.query(Account).count() == 1
        assert session.query(AccountIdentity).count() == 1
        assert session.get(User, legacy_user_id).display_name == "Legacy Aragon"


def test_idempotent_account_provisioning(
    auth_sqlite_runtime: DatabaseRuntime,
) -> None:
    with auth_sqlite_runtime.open_session() as session:
        first = resolve_or_provision_account(
            session=session,
            provider="clerk",
            provider_subject="user_unique_1",
            email="unique@example.com",
        )
        second = resolve_or_provision_account(
            session=session,
            provider="clerk",
            provider_subject="user_unique_1",
            email="unique@example.com",
        )

        assert first.id == second.id
        assert session.query(Account).count() == 1
        assert session.query(AccountIdentity).count() == 1
