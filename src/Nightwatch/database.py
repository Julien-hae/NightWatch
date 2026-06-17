"""Database connector for Postgres health checks."""

import logging
import os

import asyncpg  # type: ignore[import-untyped]

LOGGER = logging.getLogger(__name__)


def _default_database_url() -> str | None:
    """Return the DATABASE_URL env var, or None when unset."""
    return os.environ.get("DATABASE_URL")


def _normalise_dsn(url: str) -> str:
    """Strip SQLAlchemy-style ``+driver`` qualifiers so asyncpg can parse the DSN."""
    if url.startswith("postgresql+asyncpg://"):
        return "postgresql://" + url[len("postgresql+asyncpg://") :]
    if url.startswith("postgres+asyncpg://"):
        return "postgresql://" + url[len("postgres+asyncpg://") :]
    return url


class DatabaseConnector:
    """Thin Postgres connector exposing an async ``ping`` for health checks."""

    def __init__(self, database_url: str | None = None, timeout: float = 2.0) -> None:
        """Initialise the connector.

        Args:
            database_url: Postgres DSN. Falls back to the ``DATABASE_URL`` env var.
            timeout: Per-connection timeout (seconds) used when pinging.
        """
        self._database_url = database_url or _default_database_url()
        self._timeout = timeout

    @property
    def configured(self) -> bool:
        """Return True when a DSN is available."""
        return self._database_url is not None

    async def ping(self) -> bool:
        """Open a short-lived connection and run ``SELECT 1``.

        Returns:
            True when the round-trip succeeds, False on any failure.
        """
        if not self._database_url:
            return False
        dsn = _normalise_dsn(self._database_url)
        try:
            conn = await asyncpg.connect(dsn=dsn, timeout=self._timeout)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Database ping failed to connect: %s", exc)
            return False
        try:
            value = await conn.fetchval("SELECT 1")
            return bool(value == 1)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Database ping query failed: %s", exc)
            return False
        finally:
            await conn.close()
