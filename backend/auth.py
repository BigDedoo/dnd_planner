from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from jwt.algorithms import RSAAlgorithm
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from .config import Settings, settings
from .db import get_request_session
from .models import Account, AccountIdentity

logger = logging.getLogger(__name__)


class AuthenticationError(HTTPException):
    def __init__(self, detail: str = "Invalid authentication credentials") -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


@dataclass(frozen=True)
class VerifiedClaims:
    provider: str
    provider_subject: str
    email: str | None = None
    display_name: str | None = None


class TokenVerifier:
    """Interface for verifying authentication tokens and extracting claims."""

    def verify_token(self, token: str) -> VerifiedClaims:
        raise NotImplementedError


class ClerkTokenVerifier(TokenVerifier):
    """Verifies Clerk session JWTs using configured JWKS, PEM key, or secret."""

    def __init__(
        self,
        jwks_url: str | None = None,
        issuer: str | None = None,
        pem_public_key: str | None = None,
        secret_key: SecretStr | None = None,
        cache_ttl_seconds: int = 3600,
    ) -> None:
        self.jwks_url = jwks_url
        self.issuer = issuer.rstrip("/") if issuer else None
        self.pem_public_key = pem_public_key
        self.secret_key = secret_key
        self.cache_ttl_seconds = cache_ttl_seconds
        self._jwks_cache: dict[str, Any] = {}
        self._jwks_cached_at: float = 0.0

        if not self.jwks_url and self.issuer:
            self.jwks_url = urljoin(self.issuer + "/", ".well-known/jwks.json")

    def _fetch_jwks(self) -> dict[str, Any]:
        now = time.time()
        if self._jwks_cache and (now - self._jwks_cached_at < self.cache_ttl_seconds):
            return self._jwks_cache

        if not self.jwks_url:
            raise AuthenticationError("Clerk JWKS URL is not configured")

        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(self.jwks_url)
                response.raise_for_status()
                data = response.json()
                self._jwks_cache = data
                self._jwks_cached_at = now
                return data
        except Exception as exc:
            logger.error("Failed to fetch Clerk JWKS from %s: %s", self.jwks_url, exc)
            if self._jwks_cache:
                # Return stale cache if available
                return self._jwks_cache
            raise AuthenticationError("Unable to verify credentials") from exc

    def _get_signing_key(self, token: str) -> Any:
        # If explicit PEM key is configured, use it directly
        if self.pem_public_key:
            return self.pem_public_key.strip()

        # If explicit secret key is configured for symmetric testing
        if self.secret_key and not self.jwks_url and not self.issuer:
            return self.secret_key.get_secret_value()

        try:
            unverified_header = jwt.get_unverified_header(token)
        except Exception as exc:
            raise AuthenticationError("Invalid token format") from exc

        kid = unverified_header.get("kid")
        alg = unverified_header.get("alg", "RS256")

        if alg.startswith("HS"):
            if self.secret_key:
                return self.secret_key.get_secret_value()
            raise AuthenticationError("Symmetric token algorithm not allowed")

        jwks = self._fetch_jwks()
        keys = jwks.get("keys", [])

        matching_key = None
        for key in keys:
            if kid and key.get("kid") == kid:
                matching_key = key
                break
        if not matching_key and keys:
            # Fallback to the first RSA key if kid not matched
            matching_key = keys[0]

        if not matching_key:
            raise AuthenticationError("Signing key not found")

        return RSAAlgorithm.from_jwk(matching_key)

    def _fetch_user_profile(self, user_id: str) -> tuple[str | None, str | None]:
        """Optionally fetch email and name from Clerk Backend API."""
        if not self.secret_key:
            return None, None
        try:
            with httpx.Client(timeout=3.0) as client:
                headers = {
                    "Authorization": f"Bearer {self.secret_key.get_secret_value()}"
                }
                response = client.get(
                    f"https://api.clerk.com/v1/users/{user_id}",
                    headers=headers,
                )
                if response.status_code != 200:
                    return None, None
                data = response.json()
                email = None
                display_name = None

                # Primary email address
                primary_id = data.get("primary_email_address_id")
                emails = data.get("email_addresses", [])
                for e in emails:
                    if e.get("id") == primary_id:
                        email = e.get("email_address")
                        break
                if not email and emails:
                    email = emails[0].get("email_address")

                first_name = (data.get("first_name") or "").strip()
                last_name = (data.get("last_name") or "").strip()
                username = (data.get("username") or "").strip()
                if first_name or last_name:
                    display_name = f"{first_name} {last_name}".strip()
                elif username:
                    display_name = username

                return email, display_name
        except Exception as exc:
            logger.debug("Could not fetch user profile from Clerk API: %s", exc)
            return None, None

    def verify_token(self, token: str) -> VerifiedClaims:
        signing_key = self._get_signing_key(token)
        try:
            decode_options: dict[str, Any] = {
                "verify_exp": True,
                "verify_nbf": True,
                "verify_iat": True,
            }
            kwargs: dict[str, Any] = {}
            if self.issuer:
                kwargs["issuer"] = self.issuer

            # Support both RS256 (Clerk default) and HS256 (test tokens)
            algorithms = ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"]
            if self.secret_key or (
                isinstance(signing_key, str)
                and not signing_key.startswith("-----BEGIN")
            ):
                algorithms.append("HS256")

            payload = jwt.decode(
                token,
                signing_key,
                algorithms=algorithms,
                options=decode_options,
                **kwargs,
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthenticationError("Token has expired") from exc
        except jwt.InvalidTokenError as exc:
            raise AuthenticationError("Invalid token") from exc

        sub = payload.get("sub")
        if not sub or not isinstance(sub, str) or not sub.strip():
            raise AuthenticationError("Token missing valid subject")

        email: str | None = None
        display_name: str | None = None

        # Check direct claims if present in token
        if "email" in payload and isinstance(payload["email"], str):
            email = payload["email"]
        elif "primary_email" in payload and isinstance(payload["primary_email"], str):
            email = payload["primary_email"]

        if "name" in payload and isinstance(payload["name"], str):
            display_name = payload["name"]
        elif "first_name" in payload and isinstance(payload["first_name"], str):
            fn = payload.get("first_name", "").strip()
            ln = (payload.get("last_name") or "").strip()
            display_name = f"{fn} {ln}".strip() or None
        elif "username" in payload and isinstance(payload["username"], str):
            display_name = payload["username"]

        # If email or display_name not in token claims and secret_key is present, try Clerk API
        if (not email or not display_name) and self.secret_key:
            api_email, api_name = self._fetch_user_profile(sub.strip())
            email = email or api_email
            display_name = display_name or api_name

        return VerifiedClaims(
            provider="clerk",
            provider_subject=sub.strip(),
            email=email.strip().lower() if email and email.strip() else None,
            display_name=display_name.strip()
            if display_name and display_name.strip()
            else None,
        )


def extract_token_from_request(request: Request) -> str:
    """Extract authentication token from Authorization header or __session cookie."""
    auth_header = request.headers.get("Authorization")
    if auth_header:
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1].strip()
            if token:
                return token
        raise AuthenticationError(
            "Invalid Authorization header format. Expected 'Bearer <token>'"
        )

    session_cookie = request.cookies.get("__session")
    if session_cookie and session_cookie.strip():
        return session_cookie.strip()

    raise AuthenticationError("Authentication required")


def get_token_verifier(request: Request) -> TokenVerifier:
    """Build or retrieve the TokenVerifier configured for this application."""
    app_settings: Settings = getattr(request.app.state, "settings", settings)
    return ClerkTokenVerifier(
        jwks_url=app_settings.clerk_jwks_url,
        issuer=app_settings.clerk_issuer,
        pem_public_key=app_settings.clerk_pem_public_key,
        secret_key=app_settings.clerk_secret_key,
    )


def get_or_create_account(
    session: Session,
    provider: str,
    provider_subject: str,
    email: str | None = None,
    display_name: str | None = None,
) -> Account:
    """Idempotently and atomically resolve or provision an internal account.

    Safe against concurrent racing requests creating the same identity.
    """
    normalized_email = email.strip().lower() if email and email.strip() else None
    cleaned_display_name = (
        display_name.strip() if display_name and display_name.strip() else None
    )

    # 1. Check if identity already exists
    existing_identity = session.scalars(
        select(AccountIdentity)
        .options(joinedload(AccountIdentity.account))
        .where(
            AccountIdentity.provider == provider,
            AccountIdentity.provider_subject == provider_subject,
        )
    ).first()

    if existing_identity is not None:
        account = existing_identity.account
        updated = False
        if normalized_email and not account.email:
            account.email = normalized_email
            updated = True
        if cleaned_display_name and not account.display_name:
            account.display_name = cleaned_display_name
            updated = True
        if updated:
            session.flush()
        return account

    # 2. Provision new account and identity within a nested transaction (savepoint)
    try:
        with session.begin_nested():
            account = Account(
                email=normalized_email,
                display_name=cleaned_display_name,
            )
            session.add(account)
            session.flush()

            identity = AccountIdentity(
                account_id=account.id,
                provider=provider,
                provider_subject=provider_subject,
            )
            session.add(identity)
            session.flush()
            return account
    except IntegrityError:
        # Concurrent request inserted the same provider identity
        existing_identity = session.scalars(
            select(AccountIdentity)
            .options(joinedload(AccountIdentity.account))
            .where(
                AccountIdentity.provider == provider,
                AccountIdentity.provider_subject == provider_subject,
            )
        ).one()
        return existing_identity.account


def get_current_account(
    request: Request,
    session: Session = Depends(get_request_session),
    verifier: TokenVerifier = Depends(get_token_verifier),
) -> Account:
    """FastAPI dependency to authenticate requests and return the internal Account."""
    token = extract_token_from_request(request)
    claims = verifier.verify_token(token)
    account = get_or_create_account(
        session=session,
        provider=claims.provider,
        provider_subject=claims.provider_subject,
        email=claims.email,
        display_name=claims.display_name,
    )
    return account
