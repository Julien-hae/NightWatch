"""Integration tests for PaperTrader with persistent database state.

Requires ``RUN_INTEGRATION=1`` and a reachable Postgres pointed to by
``DATABASE_URL`` (e.g. the ``trade-db`` service in ``docker-compose.yml``).
Migrations are applied fresh for each test class.
"""

from __future__ import annotations

import asyncio
import os
import unittest
from decimal import Decimal
from typing import Any, Coroutine, TypeVar

import asyncpg  # type: ignore[import-untyped]
from alembic import command
from sqlalchemy import create_engine, text

from Nightwatch.db.pg_repositories import (
    PgEquitySnapshotRepo,
    PgPortfolioStateRepo,
    PgPositionRepo,
    PgProcessingCursorRepo,
)
from Nightwatch.db.repositories import PaperTraderRepos
from Nightwatch.metrics.metrics import NightwatchMetrics
from Nightwatch.models.order_factory import OrderFactoryConfig
from Nightwatch.models.paper_execution import PercentageFeeModel
from Nightwatch.models.signal import Side
from Nightwatch.pipeline.paper_trader import PaperTrader
from tests.fixtures.db import RESET_DB_SQL, alembic_cfg, to_pg_dsn
from tests.fixtures.portfolio_factory import make_portfolio
from tests.fixtures.signal_factory import make_signal

_T = TypeVar("_T")


@unittest.skipUnless(os.environ.get("RUN_INTEGRATION"), "Integration tests require RUN_INTEGRATION=1")
class TestPaperTraderWithDatabase(unittest.TestCase):
    """Test PaperTrader with persistent database state."""

    pool: asyncpg.Pool
    asyncpg_url: str
    loop: asyncio.AbstractEventLoop

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
        # A dedicated, explicit loop (rather than the deprecated get_event_loop()) keeps this
        # class isolated from whatever event-loop state an earlier test file in the same
        # discovery run left behind — get_event_loop() raised "There is no current event loop"
        # here when run after test_integration_migrations.py in a full `discover` run.
        cls.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(cls.loop)
        cls.pool = cls.loop.run_until_complete(asyncpg.create_pool(cls.asyncpg_url, min_size=1, max_size=3))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.loop.run_until_complete(cls.pool.close())
        cls.loop.close()

    # ------------------------------------------------------------------ helpers

    def run_async(self, coro: Coroutine[Any, Any, _T]) -> _T:
        return self.loop.run_until_complete(coro)

    # ------------------------------------------------------------------ tests

    def test_paper_trade_persists_position_cash_and_equity(self) -> None:
        """Execute one paper trade and verify DB shows updated position and cash."""
        metrics = NightwatchMetrics()
        portfolio = make_portfolio(cash=Decimal("2000"), last_prices={"BTC/USD": Decimal("50000")})
        position_repo = PgPositionRepo(self.pool)
        portfolio_state_repo = PgPortfolioStateRepo(self.pool)
        equity_snapshot_repo = PgEquitySnapshotRepo(self.pool)

        trader = PaperTrader(
            portfolio=portfolio,
            order_factory_config=OrderFactoryConfig(order_notional=Decimal("100")),
            fee_model=PercentageFeeModel(rate=Decimal("0.001")),
            metrics=metrics,
            repos=PaperTraderRepos(
                position=position_repo,
                portfolio_state=portfolio_state_repo,
                equity_snapshot=equity_snapshot_repo,
            ),
        )

        # Execute a BUY signal
        signal = make_signal(symbol="BTC/USD", side=Side.BUY)
        fill = trader.process_signal(signal)
        self.assertIsNotNone(fill)
        assert fill is not None

        # Persist to database
        self.run_async(trader.persist_fill_state(fill))

        # Verify position was persisted
        persisted_qty = self.run_async(position_repo.get("BTC/USD"))
        expected_qty = Decimal("100") / Decimal("50000")
        self.assertEqual(persisted_qty, expected_qty)

        # Verify cash was persisted
        persisted_cash = self.run_async(portfolio_state_repo.get_cash())
        expected_cash = Decimal("2000") - Decimal("100") - (expected_qty * Decimal("50000") * Decimal("0.001"))
        self.assertEqual(persisted_cash, expected_cash)

        # Verify equity snapshot exists
        async def check_equity_snapshot() -> tuple[Decimal, Decimal] | None:
            sql = "SELECT equity, cash FROM equity_snapshots ORDER BY ts DESC LIMIT 1"
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(sql)
            if row is None:
                return None
            return (Decimal(str(row["equity"])), Decimal(str(row["cash"])))

        snapshot = self.run_async(check_equity_snapshot())
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        snapshot_equity, snapshot_cash = snapshot
        self.assertEqual(snapshot_cash, expected_cash)
        # Equity = cash + mark-to-market of the open BTC/USD position.
        expected_equity = expected_cash + expected_qty * Decimal("50000")
        self.assertAlmostEqual(float(snapshot_equity), float(expected_equity), places=8)

    def test_multiple_fills_update_positions_and_cash(self) -> None:
        """Execute multiple trades and verify cumulative state is persisted correctly."""
        portfolio = make_portfolio(cash=Decimal("5000"), last_prices={"BTC/USD": Decimal("50000"), "ETH/USD": Decimal("2000")})
        position_repo = PgPositionRepo(self.pool)
        portfolio_state_repo = PgPortfolioStateRepo(self.pool)

        trader = PaperTrader(
            portfolio=portfolio,
            order_factory_config=OrderFactoryConfig(order_notional=Decimal("100")),
            fee_model=PercentageFeeModel(rate=Decimal("0.001")),
            repos=PaperTraderRepos(position=position_repo, portfolio_state=portfolio_state_repo),
        )

        # First trade: BUY BTC
        signal1 = make_signal(symbol="BTC/USD", side=Side.BUY)
        fill1 = trader.process_signal(signal1)
        self.assertIsNotNone(fill1)
        assert fill1 is not None
        self.run_async(trader.persist_fill_state(fill1))

        # Second trade: BUY ETH
        signal2 = make_signal(symbol="ETH/USD", side=Side.BUY)
        fill2 = trader.process_signal(signal2)
        self.assertIsNotNone(fill2)
        assert fill2 is not None
        self.run_async(trader.persist_fill_state(fill2))

        # Verify both positions persisted
        btc_qty = self.run_async(position_repo.get("BTC/USD"))
        eth_qty = self.run_async(position_repo.get("ETH/USD"))
        self.assertGreater(float(btc_qty), 0)
        self.assertGreater(float(eth_qty), 0)

        # Verify cash decreased
        persisted_cash = self.run_async(portfolio_state_repo.get_cash())
        self.assertLess(float(persisted_cash), 5000.0)
        self.assertEqual(float(persisted_cash), float(portfolio.cash))

    def test_rehydrate_restores_cash_and_positions_after_restart(self) -> None:
        """Simulate a restart: trade, persist, then rehydrate a fresh PaperTrader and assert state matches."""
        initial_cash = Decimal("3000")
        price = Decimal("50000")
        notional = Decimal("100")
        fee_rate = Decimal("0.001")

        position_repo = PgPositionRepo(self.pool)
        portfolio_state_repo = PgPortfolioStateRepo(self.pool)

        # ── First "run": trade and persist ──────────────────────────────────
        portfolio = make_portfolio(cash=initial_cash, last_prices={"BTC/USD": price})
        trader = PaperTrader(
            portfolio=portfolio,
            order_factory_config=OrderFactoryConfig(order_notional=notional),
            fee_model=PercentageFeeModel(rate=fee_rate),
            repos=PaperTraderRepos(position=position_repo, portfolio_state=portfolio_state_repo),
        )
        signal = make_signal(symbol="BTC/USD", side=Side.BUY)
        fill = trader.process_signal(signal)
        self.assertIsNotNone(fill)
        assert fill is not None
        self.run_async(trader.persist_fill_state(fill))

        expected_cash = portfolio.cash
        expected_qty = portfolio.position_qty("BTC/USD")

        # ── "Restart": fresh portfolio, then rehydrate ───────────────────────
        fresh_portfolio = make_portfolio(cash=Decimal("0"))
        rehydrated_trader = PaperTrader(
            portfolio=fresh_portfolio,
            order_factory_config=OrderFactoryConfig(order_notional=notional),
            fee_model=PercentageFeeModel(rate=fee_rate),
            repos=PaperTraderRepos(position=position_repo, portfolio_state=portfolio_state_repo),
        )
        self.run_async(rehydrated_trader.rehydrate())

        self.assertEqual(rehydrated_trader.portfolio.cash, expected_cash)
        self.assertEqual(rehydrated_trader.portfolio.position_qty("BTC/USD"), expected_qty)

    def test_rehydrate_restores_last_processed_signal_id(self) -> None:
        """persist_fill_state(signal_id) saves a cursor that rehydrate loads."""
        cursor_repo = PgProcessingCursorRepo(self.pool)
        position_repo = PgPositionRepo(self.pool)
        portfolio_state_repo = PgPortfolioStateRepo(self.pool)

        portfolio = make_portfolio(cash=Decimal("5000"), last_prices={"BTC/USD": Decimal("50000")})
        trader = PaperTrader(
            portfolio=portfolio,
            order_factory_config=OrderFactoryConfig(order_notional=Decimal("100")),
            fee_model=PercentageFeeModel(rate=Decimal("0.001")),
            repos=PaperTraderRepos(
                position=position_repo,
                portfolio_state=portfolio_state_repo,
                processing_cursor=cursor_repo,
            ),
        )

        signal = make_signal(symbol="BTC/USD", side=Side.BUY)
        fill = trader.process_signal(signal)
        assert fill is not None
        self.run_async(trader.persist_fill_state(fill, signal_id=signal.uid))

        rehydrated = PaperTrader(
            portfolio=make_portfolio(cash=Decimal("0")),
            order_factory_config=OrderFactoryConfig(order_notional=Decimal("100")),
            fee_model=PercentageFeeModel(rate=Decimal("0.001")),
            repos=PaperTraderRepos(
                position=position_repo,
                portfolio_state=portfolio_state_repo,
                processing_cursor=cursor_repo,
            ),
        )
        self.run_async(rehydrated.rehydrate())

        self.assertEqual(rehydrated.last_processed_signal_id, signal.uid)
