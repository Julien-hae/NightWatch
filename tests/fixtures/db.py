"""Shared helpers for Postgres-backed integration tests."""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from alembic.config import Config

from Nightwatch.database import to_async_dsn

# Re-exported under a neutral name; both sync (SQLAlchemy) and asyncpg accept
# the ``postgresql://`` form that ``to_async_dsn`` produces.
to_pg_dsn = to_async_dsn

# Wiping ``public`` is cheaper and exhaustive than enumerating tables.
RESET_DB_SQL = "DROP SCHEMA public CASCADE; CREATE SCHEMA public"


def alembic_cfg(database_url: str) -> Config:
    """Return an Alembic Config pointing at *database_url* using repo alembic.ini."""
    ini_path = Path(__file__).resolve().parents[2] / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def database_url_or_skip() -> str:
    """Return the ``DATABASE_URL`` env var or raise ``unittest.SkipTest``."""
    raw_url = os.environ.get("DATABASE_URL")
    if not raw_url:
        raise unittest.SkipTest("DATABASE_URL is not set")
    return raw_url
