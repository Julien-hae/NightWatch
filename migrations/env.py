"""Alembic environment configuration."""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _get_url() -> str:
    """Return a synchronous Postgres URL for Alembic.

    Reads ``DATABASE_URL`` from the environment and strips any ``+asyncpg``
    driver qualifier so the standard psycopg2 driver is used.
    Falls back to the ``sqlalchemy.url`` value in *alembic.ini*.
    """
    url = os.environ.get("DATABASE_URL") or config.get_main_option("sqlalchemy.url", "")
    for prefix, replacement in (
        ("postgresql+asyncpg://", "postgresql://"),
        ("postgres+asyncpg://", "postgresql://"),
    ):
        if url.startswith(prefix):
            return replacement + url[len(prefix) :]
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (no live DB connection required)."""
    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode against a live Postgres instance."""
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = _get_url()
    connectable = engine_from_config(cfg, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
