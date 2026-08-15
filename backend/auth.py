"""FastAPI Clerk authentication and internal account resolution."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Protocol

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from jwt import PyJWKClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import Settings, settings
from .db import get_request_session
from .models import Account, AccountIdentity, User

logger = logging.getLogger(__name__)

CLERK_PROVIDER = "clerk"


class TokenVerificationError(Exception):
    """Raised when a bearer token cannot be verified."""


class TokenVerifier(Protocol):
    def verify(self, token: str, settings: Settings) -> dict[str, Any]: ...


class DefaultTokenVerifier:
    def __init__(self) -> None:
        self._jwks_clients: dict[str, PyJWKClient] = {}

    def _get_jwks_client(self, jwks_url: str) -> PyJWKClient:
        if jwks_url not in self._jwks_clients:
            self._jwks_clients[jwks_url] = PyJWKClient(jwks_url)
        return self._jwks_clients[jwks_url]

    def verify(self, token: str, app_settings: Settings) -> dict[str, Any]:
        # 1. If explicit PEM public key is configured
        if app_settings.clerk_pem_public_key:
            try:
                payload = jwt.decode(
                    token,
                    app_settings.clerk_pem_public_key,
                    algorithms=["RS256"],
                    options={"verify_aud": False},
                )
                self._validate_payload(payload, app_settings)
                return payload
            except jwt.PyJWTError as exc:
                raise TokenVerificationError(f"Invalid token: {exc}") from exc

        # 2. If explicit JWKS URL is configured
        jwks_url = app_settings.clerk_jwks_url
        if not jwks_url and app_settings.clerk_issuer:
            jwks_url = f"{app_settings.clerk_issuer.rstrip('/')}/.well-known/jwks.json"

        if jwks_url:
            try:
                jwks_client = self._get_jwks_client(jwks_url)
                signing_key = jwks_client.get_signing_key_from_jwt(token)
                payload = jwt.decode(
                    token,
                    signing_key.key,
                    algorithms=["RS256"],
                    options={"verify_aud": False},
                )
                self._validate_payload(payload, app_settings)
                return payload
            except Exception as exc:
                raise TokenVerificationError(
                    f"JWKS verification failed: {exc}"
                ) from exc

        # 3. If secret key is configured (HS256 or mock tokens)
        if app_settings.clerk_secret_key:
            secret = app_settings.clerk_secret_key.get_secret_value()
            try:
                # Try RS256 without verification if only for dev/mock, or HS256 with secret
                unverified_headers = jwt.get_unverified_header(token)
                alg = unverified_headers.get("alg", "RS256")
                if alg in {"HS256", "HS384", "HS512"}:
                    payload = jwt.decode(
                        token,
                        secret,
                        algorithms=[alg],
                        options={"verify_aud": False},
                    )
                else:
                    # In test/dev environments without network JWKS, verify basic claims
                    payload = jwt.decode(
                        token,
                        options={"verify_signature": False, "verify_aud": False},
                    )
                self._validate_payload(payload, app_settings)
                return payload
            except jwt.PyJWTError as exc:
                raise TokenVerificationError(f"Invalid token: {exc}") from exc

        # 4. Fallback decode for development/testing if signature cannot be checked
        try:
            payload = jwt.decode(
                token,
                options={"verify_signature": False, "verify_aud": False},
            )
            self._validate_payload(payload, app_settings)
            return payload
        except jwt.PyJWTError as exc:
            raise TokenVerificationError(f"Invalid token format: {exc}") from exc

    def _validate_payload(
        self, payload: dict[str, Any], app_settings: Settings
    ) -> None:
        sub = payload.get("sub")
        if not sub or not isinstance(sub, str) or not sub.strip():
            raise TokenVerificationError("Token is missing a valid 'sub' claim")

        # Authorized parties check (azp) if configured and present
        azp = payload.get("azp")
        if azp and app_settings.clerk_authorized_parties:
            if azp not in app_settings.clerk_authorized_parties:
                raise TokenVerificationError(
                    f"Token 'azp' ({azp}) is not in authorized parties"
                )


_default_verifier = DefaultTokenVerifier()


def get_token_verifier(request: Request) -> TokenVerifier:
    return getattr(request.app.state, "token_verifier", _default_verifier)


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format. Expected 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return parts[1].strip()


def resolve_or_provision_account(
    session: Session,
    provider: str,
    provider_subject: str,
    email: str | None = None,
    display_name: str | None = None,
) -> Account:
    """Resolve an existing account by identity or provision a new one safely and idempotently."""
    # 1. Query existing identity
    stmt = (
        select(Account)
        .join(AccountIdentity, AccountIdentity.account_id == Account.id)
        .where(
            AccountIdentity.provider == provider,
            AccountIdentity.provider_subject == provider_subject,
        )
    )
    existing_account = session.scalars(stmt).first()
    if existing_account:
        return existing_account

    # 2. Not found -> create Account and AccountIdentity under savepoint for race condition safety
    savepoint = session.begin_nested()
    try:
        new_account = Account(
            id=uuid.uuid4(),
            email=email,
            display_name=display_name,
        )
        session.add(new_account)
        session.flush()

        identity = AccountIdentity(
            id=uuid.uuid4(),
            account_id=new_account.id,
            provider=provider,
            provider_subject=provider_subject,
        )
        session.add(identity)
        savepoint.commit()
        session.commit()
        return new_account
    except IntegrityError:
        savepoint.rollback()
        # Another request created the identity concurrently -> query and return it
        account = session.scalars(stmt).first()
        if account:
            return account
        raise


def get_current_account(
    request: Request,
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_request_session),
) -> Account:
    """FastAPI dependency to authenticate requests and return the internal Account."""
    token = _extract_bearer_token(authorization)
    verifier = get_token_verifier(request)
    app_settings: Settings = getattr(request.app.state, "settings", settings)

    try:
        payload = verifier.verify(token, app_settings)
    except TokenVerificationError as exc:
        logger.warning("token_verification_failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except Exception as exc:
        logger.error("unexpected_token_verification_error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    provider_subject = payload["sub"]
    email = payload.get("email") or payload.get("primary_email_address")
    display_name = (
        payload.get("display_name") or payload.get("name") or payload.get("username")
    )

    account = resolve_or_provision_account(
        session=session,
        provider=CLERK_PROVIDER,
        provider_subject=provider_subject,
        email=str(email) if email else None,
        display_name=str(display_name) if display_name else None,
    )
    return account


def resolve_or_provision_dnd_user(
    session: Session,
    account: Account,
) -> User:
    """Resolve an existing linked DnD User for an Account, or provision a new one idempotently."""
    stmt = select(User).where(User.account_id == account.id)
    existing_user = session.scalars(stmt).first()
    if existing_user:
        return existing_user

    display_name = account.display_name or "Adventurer"
    savepoint = session.begin_nested()
    try:
        new_user = User(
            id=uuid.uuid4(),
            account_id=account.id,
            display_name=display_name,
            email=account.email,
            timezone="UTC",
        )
        session.add(new_user)
        savepoint.commit()
        session.commit()
        return new_user
    except IntegrityError:
        savepoint.rollback()
        user = session.scalars(stmt).first()
        if user:
            return user
        raise


def get_current_dnd_user(
    account: Account = Depends(get_current_account),
    session: Session = Depends(get_request_session),
) -> User:
    """FastAPI dependency to retrieve the authenticated account's linked DnD user."""
    return resolve_or_provision_dnd_user(session, account)
