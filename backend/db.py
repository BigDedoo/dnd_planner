from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import Request
from pydantic import SecretStr
from sqlalchemy import URL, create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session, sessionmaker

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


class DatabaseConfigurationError(ValueError):
    """Raised for unusable database configuration without exposing credentials."""


class DatabaseReadinessError(RuntimeError):
    """Raised when a configured runtime is not ready to serve requests."""


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


def create_required_database_runtime(
    database_url: SecretStr | None,
) -> DatabaseRuntime:
    if database_url is None:
        raise DatabaseConfigurationError(
            "DATABASE_URL is required for the PostgreSQL application runtime"
        )
    return create_database_runtime(database_url)


def validate_injected_runtime(
    database_url: SecretStr | None,
    runtime: DatabaseRuntime,
) -> None:
    """Ensure an injected runtime agrees with an explicit test setting."""
    if database_url is None:
        return
    configured_url = validate_database_url(database_url)
    if configured_url != runtime.engine.url:
        raise DatabaseConfigurationError(
            "Injected database runtime does not match DATABASE_URL"
        )


def repository_head_revision() -> str:
    configuration = Config(str(REPOSITORY_ROOT / "alembic.ini"))
    head = ScriptDirectory.from_config(configuration).get_current_head()
    if head is None:
        raise DatabaseReadinessError("Repository has no Alembic head revision")
    return head


def validate_database_readiness(runtime: DatabaseRuntime) -> str:
    """Connect, execute a liveness query, and require the exact Alembic head."""
    expected_revision = repository_head_revision()
    try:
        with runtime.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            actual_revision = MigrationContext.configure(
                connection
            ).get_current_revision()
    except Exception as exc:
        raise DatabaseReadinessError(
            f"Could not validate PostgreSQL readiness at {runtime.safe_url} "
            f"({type(exc).__name__}); verify DATABASE_URL and service availability"
        ) from None

    if actual_revision != expected_revision:
        actual_label = actual_revision or "no revision"
        raise DatabaseReadinessError(
            f"PostgreSQL is at {actual_label}; expected {expected_revision}. "
            "Run 'uv run alembic upgrade head' separately before starting FastAPI."
        )
    return actual_revision


def get_request_session(request: Request) -> Iterator[Session]:
    """Yield one app-specific Session and always close or roll it back safely."""
    runtime: DatabaseRuntime = request.app.state.database_runtime
    session = runtime.open_session()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
