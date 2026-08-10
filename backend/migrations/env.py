from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import URL

from backend.config import Settings
from backend.db import create_database_runtime, validate_database_url
from backend.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> URL:
    injected_url = config.attributes.get("database_url")
    if injected_url is not None:
        return validate_database_url(str(injected_url))

    settings = Settings()
    if settings.database_url is None:
        raise RuntimeError(
            "DATABASE_URL is required for Alembic and must use postgresql+psycopg"
        )
    return validate_database_url(settings.database_url)


def run_migrations_offline() -> None:
    database_url = _database_url()
    context.configure(
        url=database_url.render_as_string(hide_password=False),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    database_url = _database_url()
    runtime = create_database_runtime(
        database_url.render_as_string(hide_password=False)
    )
    try:
        with runtime.engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )

            with context.begin_transaction():
                context.run_migrations()
    finally:
        runtime.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
