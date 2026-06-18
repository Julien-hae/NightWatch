"""Integration tests for Postgres-backed repository implementations.

Requires ``RUN_INTEGRATION=1`` and a reachable Postgres pointed to by
``DATABASE_URL`` (e.g. the ``trade-db`` service in ``docker-compose.yml``).
Migrations are applied fresh for each test class.
"""

from __future__ import annotations

import asyncio
import os
import unittest
import uuid
from decimal import Decimal
from typing import Any, Coroutine, TypeVar

import asyncpg  # type: ignore[import-untyped]
from alembic import command
from sqlalchemy import create_engine, text

from Nightwatch.db.pg_repositories import (
    PgEquitySnapshotRepo,
    PgFillRepo,
    PgOrderRepo,
    PgPortfolioStateRepo,
    PgPositionRepo,
    PgProcessingCursorRepo,
    PgSignalRepo,
)
from Nightwatch.db.repositories import OrderCreateResult
from tests.fixtures.db import RESET_DB_SQL, alembic_cfg, to_pg_dsn
from tests.fixtures.fill_factory import make_fill
from tests.fixtures.order_factory import make_order
from tests.fixtures.signal_factory import make_signal

_T = TypeVar("_T")


@unittest.skipUnless(os.environ.get("RUN_INTEGRATION"), "Integration tests require RUN_INTEGRATION=1")
class TestPgRepositories(unittest.TestCase):
    """Drive Postgres repositories against a live database."""

    pool: asyncpg.Pool
    asyncpg_url: str

    @classmethod
    def setUpClass(cls) -> None:
        raw_url = os.environ.get("DATABASE_URL")
        if not raw_url:
            raise unittest.SkipTest("DATABASE_URL is not set")

        sync_url = to_pg_dsn(raw_url)
        engine = create_engine(sync_url)

        # Fresh schema for this test run.
        with engine.connect() as conn:
            conn.execute(text(RESET_DB_SQL))
            conn.commit()

        command.upgrade(alembic_cfg(sync_url), "head")
        engine.dispose()

        cls.asyncpg_url = to_pg_dsn(raw_url)
        cls.pool = asyncio.get_event_loop().run_until_complete(asyncpg.create_pool(cls.asyncpg_url, min_size=1, max_size=3))

    @classmethod
    def tearDownClass(cls) -> None:
        asyncio.get_event_loop().run_until_complete(cls.pool.close())

    # ------------------------------------------------------------------ helpers

    def run_async(self, coro: Coroutine[Any, Any, _T]) -> _T:
        return asyncio.get_event_loop().run_until_complete(coro)

    # ------------------------------------------------------------------ signals

    def test_save_signal_persists_and_returns_on_query(self) -> None:
        repo = PgSignalRepo(self.pool)
        signal = make_signal(symbol="ETH/USD")

        self.run_async(repo.save(signal))

        async def _fetch() -> dict[str, Any]:
            async with self.pool.acquire() as conn:
                return dict(await conn.fetchrow("SELECT * FROM signals WHERE signal_id = $1", signal.uid))

        row = self.run_async(_fetch())
        self.assertEqual(str(row["signal_id"]), str(signal.uid))
        self.assertEqual(row["symbol"], "ETH/USD")
        self.assertEqual(row["side"], signal.side.value)

    def test_save_signal_upsert_updates_existing(self) -> None:
        repo = PgSignalRepo(self.pool)
        signal = make_signal(symbol="BTC/USD", strength=10.0)

        self.run_async(repo.save(signal))

        updated = signal.model_copy(update={"strength": 99.0})
        self.run_async(repo.save(updated))

        async def _count() -> int:
            async with self.pool.acquire() as conn:
                return int(await conn.fetchval("SELECT COUNT(*) FROM signals WHERE signal_id = $1", signal.uid))

        self.assertEqual(self.run_async(_count()), 1)

    # ------------------------------------------------------------------ orders

    def test_create_order_returns_created(self) -> None:
        repo = PgOrderRepo(self.pool)
        order = make_order()

        result = self.run_async(repo.create(order))

        self.assertEqual(result, OrderCreateResult.CREATED)

    def test_create_order_duplicate_idempotency_key_returns_already_exists(self) -> None:
        repo = PgOrderRepo(self.pool)
        signal_id = uuid.uuid4()
        first = make_order(signal_id=signal_id)
        second = make_order(signal_id=signal_id)

        first_result = self.run_async(repo.create(first))
        second_result = self.run_async(repo.create(second))

        self.assertEqual(first_result, OrderCreateResult.CREATED)
        self.assertEqual(second_result, OrderCreateResult.ALREADY_EXISTS)

        async def _count() -> int:
            async with self.pool.acquire() as conn:
                return int(await conn.fetchval("SELECT COUNT(*) FROM orders WHERE signal_id = $1", signal_id))

        self.assertEqual(self.run_async(_count()), 1)

    def test_create_order_persists_fields(self) -> None:
        repo = PgOrderRepo(self.pool)
        order = make_order(symbol="SOL/USD")

        self.run_async(repo.create(order))

        async def _fetch() -> dict[str, Any]:
            async with self.pool.acquire() as conn:
                return dict(await conn.fetchrow("SELECT * FROM orders WHERE order_id = $1", order.order_id))

        row = self.run_async(_fetch())
        self.assertEqual(row["symbol"], "SOL/USD")
        self.assertEqual(row["side"], order.side.value)

    # ------------------------------------------------------------------ fills

    def test_append_fill_persists_fields(self) -> None:
        order_repo = PgOrderRepo(self.pool)
        fill_repo = PgFillRepo(self.pool)

        order = make_order()
        self.run_async(order_repo.create(order))

        fill = make_fill(order_id=order.order_id, symbol="BTC/USD")
        self.run_async(fill_repo.append(fill))

        async def _fetch() -> dict[str, Any]:
            async with self.pool.acquire() as conn:
                return dict(await conn.fetchrow("SELECT * FROM fills WHERE fill_id = $1", fill.fill_id))

        row = self.run_async(_fetch())
        self.assertEqual(str(row["fill_id"]), str(fill.fill_id))
        self.assertEqual(row["symbol"], "BTC/USD")

    # ------------------------------------------------------------------ positions

    def test_get_position_returns_zero_when_absent(self) -> None:
        repo = PgPositionRepo(self.pool)
        qty = self.run_async(repo.get("UNKNOWN/USD"))
        self.assertEqual(qty, Decimal("0"))

    def test_upsert_position_insert_and_update(self) -> None:
        repo = PgPositionRepo(self.pool)
        symbol = f"TEST/{uuid.uuid4().hex[:6].upper()}"

        self.run_async(repo.upsert(symbol, Decimal("0.5")))
        self.assertEqual(self.run_async(repo.get(symbol)), Decimal("0.5"))

        self.run_async(repo.upsert(symbol, Decimal("1.2")))
        self.assertEqual(self.run_async(repo.get(symbol)), Decimal("1.2"))

    # ------------------------------------------------------------------ equity snapshots

    def test_insert_equity_snapshot_persists(self) -> None:
        repo = PgEquitySnapshotRepo(self.pool)

        self.run_async(repo.insert(equity=Decimal("10000.00"), cash=Decimal("5000.00")))

        async def _count() -> int:
            async with self.pool.acquire() as conn:
                return int(await conn.fetchval("SELECT COUNT(*) FROM equity_snapshots WHERE equity = $1", Decimal("10000.00")))

        self.assertGreaterEqual(self.run_async(_count()), 1)

    # ------------------------------------------------------------------ portfolio_state

    def test_save_cash_then_get_cash_round_trip(self) -> None:
        repo = PgPortfolioStateRepo(self.pool)

        self.run_async(repo.save_cash(Decimal("12345.67")))
        self.assertEqual(self.run_async(repo.get_cash()), Decimal("12345.67"))

        self.run_async(repo.save_cash(Decimal("890.12")))
        self.assertEqual(self.run_async(repo.get_cash()), Decimal("890.12"))

        async def _count() -> int:
            async with self.pool.acquire() as conn:
                return int(await conn.fetchval("SELECT COUNT(*) FROM portfolio_state"))

        self.assertEqual(self.run_async(_count()), 1)

    # ------------------------------------------------------------------ processing_cursor

    def test_processing_cursor_round_trip(self) -> None:
        repo = PgProcessingCursorRepo(self.pool)

        self.assertIsNone(self.run_async(repo.get_last_signal_id()))

        sid = uuid.uuid4()
        self.run_async(repo.save_last_signal_id(sid))
        self.assertEqual(self.run_async(repo.get_last_signal_id()), sid)

        sid2 = uuid.uuid4()
        self.run_async(repo.save_last_signal_id(sid2))
        self.assertEqual(self.run_async(repo.get_last_signal_id()), sid2)

        async def _count() -> int:
            async with self.pool.acquire() as conn:
                return int(await conn.fetchval("SELECT COUNT(*) FROM processing_cursor"))

        self.assertEqual(self.run_async(_count()), 1)


if __name__ == "__main__":
    unittest.main()
