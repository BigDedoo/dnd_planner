"""Official Clerk request authentication and internal account resolution."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Callable, Protocol

from clerk_backend_api.security import authenticate_request
from clerk_backend_api.security.types import (
    AuthenticateRequestOptions,
    RequestState,
    TokenType,
)
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import Settings, settings
from .db import get_request_session
from .models import Account, AccountIdentity, User

logger = logging.getLogger(__name__)

CLERK_PROVIDER = "clerk"


class ClerkAuthenticationError(Exception):
    """Raised when Clerk cannot authenticate a request safely."""

    def __init__(self, category: str) -> None:
        super().__init__("Clerk request authentication failed")
        self.category = category


@dataclass(frozen=True)
class VerifiedClerkSession:
    """The verified identity fields consumed by the application boundary."""

    subject: str
    email: str | None = None
    display_name: str | None = None


class RequestAuthenticator(Protocol):
    def authenticate(
        self,
        request: Request,
        app_settings: Settings,
    ) -> VerifiedClerkSession: ...


ClerkAuthenticateRequest = Callable[
    [Request, AuthenticateRequestOptions],
    RequestState,
]


class ClerkSDKRequestAuthenticator:
    """Authenticate Clerk session tokens through the official backend SDK."""

    def __init__(
        self,
        authenticate_request_fn: ClerkAuthenticateRequest = authenticate_request,
    ) -> None:
        self._authenticate_request = authenticate_request_fn

    def authenticate(
        self,
        request: Request,
        app_settings: Settings,
    ) -> VerifiedClerkSession:
        secret = app_settings.clerk_secret_key
        if secret is None or not secret.get_secret_value().strip():
            raise ClerkAuthenticationError("configuration_missing_secret")
        if not app_settings.clerk_authorized_parties:
            raise ClerkAuthenticationError("configuration_missing_authorized_parties")

        options = AuthenticateRequestOptions(
            secret_key=secret.get_secret_value(),
            authorized_parties=list(app_settings.clerk_authorized_parties),
            accepts_token=[TokenType.SESSION_TOKEN.value],
        )
        try:
            request_state = self._authenticate_request(request, options)
        except Exception as exc:
            raise ClerkAuthenticationError("sdk_error") from exc

        if not request_state.is_signed_in or request_state.payload is None:
            raise ClerkAuthenticationError("request_rejected")

        payload = request_state.payload
        subject = payload.get("sub")
        if not isinstance(subject, str) or not subject.strip():
            raise ClerkAuthenticationError("verified_session_missing_subject")

        email = payload.get("email") or payload.get("primary_email_address")
        display_name = (
            payload.get("display_name")
            or payload.get("name")
            or payload.get("username")
        )
        return VerifiedClerkSession(
            subject=subject.strip(),
            email=str(email) if email else None,
            display_name=str(display_name) if display_name else None,
        )


_default_authenticator = ClerkSDKRequestAuthenticator()


def get_request_authenticator(request: Request) -> RequestAuthenticator:
    return getattr(
        request.app.state,
        "request_authenticator",
        _default_authenticator,
    )


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
    """Resolve an identity or provision its internal account idempotently."""
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
        account = session.scalars(stmt).first()
        if account:
            return account
        raise


def get_current_account(
    request: Request,
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_request_session),
) -> Account:
    """Authenticate a Clerk session and return its stable internal account."""
    _extract_bearer_token(authorization)
    authenticator = get_request_authenticator(request)
    app_settings: Settings = getattr(request.app.state, "settings", settings)

    try:
        verified_session = authenticator.authenticate(request, app_settings)
    except ClerkAuthenticationError as exc:
        logger.warning("clerk_authentication_failed category=%s", exc.category)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except Exception:
        logger.error("clerk_authentication_failed category=unexpected_error")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    return resolve_or_provision_account(
        session=session,
        provider=CLERK_PROVIDER,
        provider_subject=verified_session.subject,
        email=verified_session.email,
        display_name=verified_session.display_name,
    )


def get_current_dnd_user(
    account: Account = Depends(get_current_account),
    session: Session = Depends(get_request_session),
) -> User:
    """Return the explicitly linked DnD user for the verified account."""
    user = session.scalars(select(User).where(User.account_id == account.id)).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated account is not linked to a DnD user",
        )
    return user
