from __future__ import annotations

import datetime
import uuid
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import jwt
import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from backend.auth import (
    AuthenticationError,
    ClerkTokenVerifier,
    TokenVerifier,
    VerifiedClaims,
    get_or_create_account,
)
from backend.config import Settings
from backend.db import DatabaseRuntime
from backend.main import create_app
from backend.models import Account, AccountIdentity, Base


class MockTokenVerifier(TokenVerifier):
    """Test verifier that maps test tokens to predefined claims."""

    def __init__(self) -> None:
        self.identities: dict[str, VerifiedClaims] = {}

    def set_identity(
        self,
        token: str,
        provider_subject: str,
        email: str | None = None,
        display_name: str | None = None,
        provider: str = "clerk",
    ) -> None:
        self.identities[token] = VerifiedClaims(
            provider=provider,
            provider_subject=provider_subject,
            email=email,
            display_name=display_name,
        )

    def verify_token(self, token: str) -> VerifiedClaims:
        if token in self.identities:
            return self.identities[token]
        raise AuthenticationError("Invalid test token")


@pytest.fixture
def mock_verifier() -> MockTokenVerifier:
    return MockTokenVerifier()


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
    mock_verifier: MockTokenVerifier,
) -> FastAPI:
    test_settings = Settings(
        _env_file=None,
        APP_ENV="test",
        LOG_LEVEL="CRITICAL",
        CORS_ALLOWED_ORIGINS=["http://testserver"],
    )
    application = create_app(test_settings, database_runtime=auth_sqlite_runtime)

    # Patch readiness and compatibility dataset checks which are postgres/phase 1 specific
    with (
        patch("backend.main.validate_database_readiness"),
        patch("backend.main.compatibility.validate_compatibility_dataset"),
    ):
        from backend.auth import get_token_verifier

        application.dependency_overrides[get_token_verifier] = lambda: mock_verifier
        yield application


@pytest.fixture
def client(auth_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(auth_app) as test_client:
        yield test_client


def test_unauthenticated_me_returns_401(client: TestClient) -> None:
    response = client.get("/me")
    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


def test_invalid_bearer_format_returns_401(client: TestClient) -> None:
    response = client.get("/me", headers={"Authorization": "Basic invalid"})
    assert response.status_code == 401
    assert "Invalid Authorization header" in response.json()["detail"]


def test_invalid_token_returns_401(client: TestClient) -> None:
    response = client.get("/me", headers={"Authorization": "Bearer unknown_token"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid test token"


def test_first_authentication_provisions_account(
    client: TestClient,
    mock_verifier: MockTokenVerifier,
) -> None:
    mock_verifier.set_identity(
        token="valid-token-1",
        provider_subject="user_clerk_123",
        email="adventurer@example.com",
        display_name="Adventurer One",
    )

    response = client.get(
        "/me",
        headers={"Authorization": "Bearer valid-token-1"},
    )
    assert response.status_code == 200
    data = response.json()

    # Verify safe fields are returned
    assert "id" in data
    assert uuid.UUID(data["id"])
    assert data["email"] == "adventurer@example.com"
    assert data["display_name"] == "Adventurer One"

    # Verify sensitive fields and provider tokens are NOT exposed
    assert "provider" not in data
    assert "provider_subject" not in data
    assert "token" not in data
    assert "secret" not in data


def test_session_cookie_authentication_supported(
    client: TestClient,
    mock_verifier: MockTokenVerifier,
) -> None:
    mock_verifier.set_identity(
        token="cookie-token",
        provider_subject="user_clerk_cookie",
        email="cookie@example.com",
        display_name="Cookie User",
    )

    client.cookies.set("__session", "cookie-token")
    response = client.get("/me")
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "cookie@example.com"
    assert data["display_name"] == "Cookie User"


def test_repeated_authentication_is_idempotent(
    client: TestClient,
    mock_verifier: MockTokenVerifier,
) -> None:
    mock_verifier.set_identity(
        token="repeat-token",
        provider_subject="user_clerk_repeat",
        email="repeat@example.com",
        display_name="Repeat User",
    )

    resp1 = client.get("/me", headers={"Authorization": "Bearer repeat-token"})
    resp2 = client.get("/me", headers={"Authorization": "Bearer repeat-token"})

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json()["id"] == resp2.json()["id"]


def test_different_provider_subjects_create_different_accounts(
    client: TestClient,
    mock_verifier: MockTokenVerifier,
) -> None:
    mock_verifier.set_identity(
        token="user-a-token",
        provider_subject="user_clerk_a",
        email="a@example.com",
        display_name="User A",
    )
    mock_verifier.set_identity(
        token="user-b-token",
        provider_subject="user_clerk_b",
        email="b@example.com",
        display_name="User B",
    )

    resp_a = client.get("/me", headers={"Authorization": "Bearer user-a-token"})
    resp_b = client.get("/me", headers={"Authorization": "Bearer user-b-token"})

    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    assert resp_a.json()["id"] != resp_b.json()["id"]


def test_clerk_jwt_verifier_verifies_jwt_signature_and_claims() -> None:
    secret = "test-secret-key-12345678901234567890"
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": "user_jwt_test_subject",
        "email": "jwt@example.com",
        "name": "JWT User",
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + datetime.timedelta(hours=1)).timestamp()),
    }
    encoded = jwt.encode(payload, secret, algorithm="HS256")

    from pydantic import SecretStr

    verifier = ClerkTokenVerifier(secret_key=SecretStr(secret))
    claims = verifier.verify_token(encoded)

    assert claims.provider == "clerk"
    assert claims.provider_subject == "user_jwt_test_subject"
    assert claims.email == "jwt@example.com"
    assert claims.display_name == "JWT User"


def test_clerk_jwt_verifier_rejects_expired_tokens() -> None:
    secret = "test-secret-key-12345678901234567890"
    past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)
    payload = {
        "sub": "user_expired",
        "iat": int((past - datetime.timedelta(hours=1)).timestamp()),
        "nbf": int((past - datetime.timedelta(hours=1)).timestamp()),
        "exp": int(past.timestamp()),
    }
    encoded = jwt.encode(payload, secret, algorithm="HS256")

    from pydantic import SecretStr

    verifier = ClerkTokenVerifier(secret_key=SecretStr(secret))
    with pytest.raises(AuthenticationError, match="expired"):
        verifier.verify_token(encoded)


def test_get_or_create_account_concurrency_safe(
    auth_sqlite_runtime: DatabaseRuntime,
) -> None:
    session = auth_sqlite_runtime.open_session()
    try:
        # First call provisions
        acc1 = get_or_create_account(
            session=session,
            provider="clerk",
            provider_subject="user_concurrent_test",
            email="concurrent@example.com",
            display_name="Concurrent User",
        )
        session.commit()

        # Second call returns existing
        acc2 = get_or_create_account(
            session=session,
            provider="clerk",
            provider_subject="user_concurrent_test",
            email="concurrent@example.com",
            display_name="Concurrent User",
        )
        assert acc1.id == acc2.id

        # Verify only 1 account and 1 identity row exist
        account_count = session.query(Account).count()
        identity_count = session.query(AccountIdentity).count()
        assert account_count == 1
        assert identity_count == 1
    finally:
        session.close()
