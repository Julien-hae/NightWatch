"""Bootstrap the persistence layer: apply migrations, open a pool, build repositories."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path

import asyncpg  # type: ignore[import-untyped]
from alembic import command
from alembic.config import Config

from Nightwatch.db.database import to_async_dsn
from Nightwatch.db.pg_repositories import (
    PgAtomicTradeWriter,
    PgEquitySnapshotRepo,
    PgFillRepo,
    PgOrderRepo,
    PgPortfolioStateRepo,
    PgPositionRepo,
    PgProcessingCursorRepo,
    PgSignalRepo,
)
from Nightwatch.metrics.metrics import NightwatchMetrics

LOGGER = logging.getLogger(__name__)

# Arbitrary 64-bit key for the singleton advisory lock (see bootstrap_persistence).
# Must not collide with any other pg_advisory_lock key ever taken against this
# database — nothing else in this codebase uses advisory locks today.
_SINGLETON_LOCK_KEY = 727_363_514_002_026


class SingletonLockError(RuntimeError):
    """Raised when another process already holds the trade-service singleton lock.

    Signal.uid/Order.signal_id are generated per-process (uuid4(), not derived from
    the tick itself), so two concurrently running instances reacting to the same
    market data would each create their own, non-conflicting orders — silently
    doubling every position and cash movement with nothing to catch it. This lock
    makes that scenario a loud startup failure instead of a silent one.
    """


@dataclass
class PersistenceContext:
    """Container for the pool and every Postgres repository the bot needs."""

    pool: asyncpg.Pool
    signal_repo: PgSignalRepo
    order_repo: PgOrderRepo
    fill_repo: PgFillRepo
    position_repo: PgPositionRepo
    portfolio_state_repo: PgPortfolioStateRepo
    equity_snapshot_repo: PgEquitySnapshotRepo
    processing_cursor_repo: PgProcessingCursorRepo
    trade_writer: PgAtomicTradeWriter
    _lock_connection: asyncpg.Connection

    async def close(self) -> None:
        """Release the singleton advisory lock, then close the connection pool."""
        try:
            await self._lock_connection.execute("SELECT pg_advisory_unlock($1)", _SINGLETON_LOCK_KEY)
        finally:
            await self._lock_connection.close()
        await self.pool.close()


def _migrations_dir() -> Path:
    """Locate the ``migrations/`` directory via $MIGRATIONS_DIR or by walking up."""
    env_override = os.environ.get("MIGRATIONS_DIR")
    if env_override:
        return Path(env_override)
    for ancestor in Path(__file__).resolve().parents:
        candidate = ancestor / "migrations"
        if (candidate / "env.py").is_file():
            return candidate
    raise FileNotFoundError("Could not locate migrations directory")


def _alembic_config(database_url: str) -> Config:
    """Build an Alembic Config without requiring alembic.ini."""
    cfg = Config()
    cfg.set_main_option("script_location", str(_migrations_dir()))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def apply_migrations(database_url: str) -> None:
    """Run ``alembic upgrade head`` against *database_url* and log on success."""
    cfg = _alembic_config(to_async_dsn(database_url))
    command.upgrade(cfg, "head")
    LOGGER.info("Applied migrations")


async def bootstrap_persistence(
    database_url: str,
    metrics: NightwatchMetrics | None = None,
    pool_min_size: int = 1,
    pool_max_size: int = 5,
) -> PersistenceContext:
    """Apply migrations, open an asyncpg pool, and build every Pg repository.

    Also takes a session-level Postgres advisory lock on a dedicated connection
    (held for the lifetime of the returned :class:`PersistenceContext`) to
    enforce that only one instance of this service runs against a given
    database at a time. See :class:`SingletonLockError` for why this matters.

    Args:
        database_url: Postgres DSN. May use ``postgresql+asyncpg://`` form.
        metrics: Optional metrics instance. Sets ``db_up`` on success and
            failure, and is passed into each repository for write-error tracking.
        pool_min_size: Minimum connections held in the pool.
        pool_max_size: Maximum connections held in the pool.

    Returns:
        A :class:`PersistenceContext` holding the pool and configured repos.

    Raises:
        SingletonLockError: Another process already holds the singleton lock
            against this database.
        Exception: Re-raises any other failure encountered; ``db_up`` is set
            to ``0`` before re-raising when *metrics* is provided.
    """
    pool: asyncpg.Pool | None = None
    lock_connection: asyncpg.Connection | None = None
    try:
        await asyncio.to_thread(apply_migrations, database_url)
        pool = await asyncpg.create_pool(
            to_async_dsn(database_url),
            min_size=pool_min_size,
            max_size=pool_max_size,
        )

        # A dedicated connection, outside the pool, so the lock is held for this
        # context's whole lifetime rather than released back to the pool the moment
        # whichever coroutine acquired it finishes.
        lock_connection = await asyncpg.connect(to_async_dsn(database_url))
        acquired = await lock_connection.fetchval("SELECT pg_try_advisory_lock($1)", _SINGLETON_LOCK_KEY)
        if not acquired:
            raise SingletonLockError(
                "Another trade-service instance already holds the singleton lock on this database. "
                "Running two instances against the same Postgres and Kraken feed would double-trade — "
                "stop the other instance first."
            )
    except Exception:
        if metrics is not None:
            metrics.db_up.set(0)
        if lock_connection is not None:
            await lock_connection.close()
        if pool is not None:
            await pool.close()
        raise

    LOGGER.info("DB connected; singleton lock acquired")
    if metrics is not None:
        metrics.db_up.set(1)

    return PersistenceContext(
        pool=pool,
        signal_repo=PgSignalRepo(pool, metrics=metrics),
        order_repo=PgOrderRepo(pool, metrics=metrics),
        fill_repo=PgFillRepo(pool, metrics=metrics),
        position_repo=PgPositionRepo(pool, metrics=metrics),
        portfolio_state_repo=PgPortfolioStateRepo(pool, metrics=metrics),
        equity_snapshot_repo=PgEquitySnapshotRepo(pool, metrics=metrics),
        processing_cursor_repo=PgProcessingCursorRepo(pool, metrics=metrics),
        trade_writer=PgAtomicTradeWriter(pool, metrics=metrics),
        _lock_connection=lock_connection,
    )
