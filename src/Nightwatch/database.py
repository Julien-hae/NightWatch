"""Database connector for Postgres health checks."""

import logging
import os

import asyncpg  # type: ignore[import-untyped]

LOGGER = logging.getLogger(__name__)


def _default_database_url() -> str | None:
    """Return the DATABASE_URL env var, or None when unset."""
    return os.environ.get("DATABASE_URL")


def to_async_dsn(url: str) -> str:
    """Return a DSN suitable for asyncpg (strips ``+asyncpg`` driver qualifiers)."""
    if url.startswith("postgresql+asyncpg://"):
        return "postgresql://" + url[len("postgresql+asyncpg://") :]
    if url.startswith("postgres+asyncpg://"):
        return "postgresql://" + url[len("postgres+asyncpg://") :]
    return url


class DatabaseConnector:
    """Thin Postgres connector exposing an async ``ping`` for health checks."""

    def __init__(
        self,
        database_url: str | None = None,
        timeout: float = 2.0,
        pool: asyncpg.Pool | None = None,
    ) -> None:
        """Initialise the connector.

        Args:
            database_url: Postgres DSN. Falls back to the ``DATABASE_URL`` env var.
            timeout: Per-connection timeout (seconds) used when pinging.
            pool: Optional pre-built asyncpg pool. When provided, ``ping`` reuses
                it instead of opening a fresh connection per call.
        """
        self._database_url = database_url or _default_database_url()
        self._timeout = timeout
        self._pool = pool

    @property
    def configured(self) -> bool:
        """Return True when either a DSN or a pool is available."""
        return self._pool is not None or self._database_url is not None

    async def ping(self) -> bool:
        """Run ``SELECT 1`` against Postgres.

        Reuses the injected pool when available; otherwise opens a short-lived
        connection from the DSN.

        Returns:
            True when the round-trip succeeds, False on any failure.
        """
        if self._pool is not None:
            try:
                value = await self._pool.fetchval("SELECT 1", timeout=self._timeout)
                return bool(value == 1)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Database pool ping failed: %s", exc)
                return False

        if not self._database_url:
            return False
        dsn = to_async_dsn(self._database_url)
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
