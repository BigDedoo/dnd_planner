from __future__ import annotations

from pydantic import SecretStr
from sqlalchemy import URL, create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session, sessionmaker


class DatabaseConfigurationError(ValueError):
    """Raised for unusable database configuration without exposing credentials."""


def _reveal_url(database_url: str | SecretStr) -> str:
    if isinstance(database_url, SecretStr):
        return database_url.get_secret_value()
    return database_url


def validate_database_url(database_url: str | SecretStr) -> URL:
    """Parse the new runtime URL while keeping diagnostics password-safe."""
    raw_url = _reveal_url(database_url).strip()
    if not raw_url:
        raise DatabaseConfigurationError("DATABASE_URL must not be empty")

    try:
        parsed_url = make_url(raw_url)
    except (ArgumentError, TypeError, ValueError):
        raise DatabaseConfigurationError(
            "DATABASE_URL must be a valid SQLAlchemy URL"
        ) from None

    if parsed_url.drivername != "postgresql+psycopg":
        raise DatabaseConfigurationError(
            "DATABASE_URL must use the postgresql+psycopg driver"
        )
    if not parsed_url.database:
        raise DatabaseConfigurationError("DATABASE_URL must name a PostgreSQL database")
    return parsed_url


def redact_database_url(database_url: str | SecretStr | URL) -> str:
    """Render a configured URL without its password."""
    parsed_url = (
        database_url
        if isinstance(database_url, URL)
        else validate_database_url(database_url)
    )
    return parsed_url.render_as_string(hide_password=True)


class DatabaseRuntime:
    """One isolated synchronous SQLAlchemy engine and session factory."""

    __slots__ = ("engine", "session_factory", "safe_url")

    def __init__(self, engine: Engine, safe_url: str) -> None:
        self.engine = engine
        self.session_factory: sessionmaker[Session] = sessionmaker(
            bind=engine,
            class_=Session,
            expire_on_commit=False,
        )
        self.safe_url = safe_url

    def open_session(self) -> Session:
        return self.session_factory()

    def dispose(self) -> None:
        self.engine.dispose()

    def __repr__(self) -> str:
        return f"DatabaseRuntime(url={self.safe_url!r})"


def create_database_runtime(database_url: str | SecretStr) -> DatabaseRuntime:
    """Build, but do not connect, migrate, or create schema objects."""
    parsed_url = validate_database_url(database_url)
    safe_url = redact_database_url(parsed_url)
    try:
        engine = create_engine(parsed_url, pool_pre_ping=True)
    except Exception as exc:
        raise DatabaseConfigurationError(
            f"Could not configure PostgreSQL engine for {safe_url} "
            f"({type(exc).__name__})"
        ) from None
    return DatabaseRuntime(engine=engine, safe_url=safe_url)
