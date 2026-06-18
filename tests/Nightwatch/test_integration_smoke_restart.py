"""End-to-end smoke test: trade → persist atomically → rehydrate after restart.

Exercises the full production persistence path through
``PaperTrader.process_and_persist`` (which uses ``PgAtomicTradeWriter``)
followed by a fresh ``PaperTrader.rehydrate`` to prove that signals,
orders, fills, position, cash and processing cursor all survive a restart.
"""

from __future__ import annotations

import asyncio
import os
import unittest
from decimal import Decimal
from typing import Any, Coroutine, TypeVar

from alembic import command
from sqlalchemy import create_engine, text

from Nightwatch.bootstrap import bootstrap_persistence
from Nightwatch.metrics import NightwatchMetrics
from Nightwatch.models.order_factory import OrderFactoryConfig
from Nightwatch.models.paper_execution import PercentageFeeModel
from Nightwatch.models.portfolio import Portfolio
from Nightwatch.models.signal import Side
from Nightwatch.paper_trader import PaperTrader
from Nightwatch.repositories import PaperTraderRepos
from tests.fixtures.db import RESET_DB_SQL, alembic_cfg, to_pg_dsn
from tests.fixtures.signal_factory import make_signal

_T = TypeVar("_T")


@unittest.skipUnless(
    os.environ.get("RUN_INTEGRATION") and os.environ.get("DATABASE_URL"),
    "Integration tests require RUN_INTEGRATION=1 and DATABASE_URL",
)
class TestRestartRestoreSmoke(unittest.TestCase):
    """Prove that a full trade survives a simulated process restart."""

    database_url: str

    @classmethod
    def setUpClass(cls) -> None:
        raw_url = os.environ.get("DATABASE_URL")
        assert raw_url is not None
        cls.database_url = raw_url

        sync_url = to_pg_dsn(raw_url)
        engine = create_engine(sync_url)
        with engine.connect() as conn:
            conn.execute(text(RESET_DB_SQL))
            conn.commit()
        command.upgrade(alembic_cfg(sync_url), "head")
        engine.dispose()

    def _run(self, coro: Coroutine[Any, Any, _T]) -> _T:
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_trade_then_restart_restores_state(self) -> None:
        """Run a trade through one pipeline, tear it down, restore in a second."""
        initial_cash = Decimal("3000")
        price = Decimal("50000")
        order_notional = Decimal("100")
        fee_rate = Decimal("0.001")

        # ── Boot #1: full bootstrap → trade → persist ───────────────────────
        metrics_a = NightwatchMetrics()
        ctx_a = self._run(bootstrap_persistence(self.database_url, metrics=metrics_a))
        try:
            portfolio_a = Portfolio(cash=initial_cash, positions={}, last_prices={"BTC/USD": price})
            trader_a = PaperTrader(
                portfolio=portfolio_a,
                order_factory_config=OrderFactoryConfig(order_notional=order_notional),
                fee_model=PercentageFeeModel(rate=fee_rate),
                metrics=metrics_a,
                repos=PaperTraderRepos.from_context(ctx_a),
            )
            self._run(trader_a.rehydrate())  # no-op on fresh DB
            signal = make_signal(symbol="BTC/USD", side=Side.BUY)
            fill = self._run(trader_a.process_and_persist(signal))
            self.assertIsNotNone(fill)

            expected_cash = portfolio_a.cash
            expected_qty = portfolio_a.position_qty("BTC/USD")
            expected_signal_id = signal.uid

            # DB rows for signal/order/fill must all exist.
            async def _counts() -> dict[str, int]:
                async with ctx_a.pool.acquire() as conn:
                    return {
                        "signals": int(await conn.fetchval("SELECT COUNT(*) FROM signals")),
                        "orders": int(await conn.fetchval("SELECT COUNT(*) FROM orders")),
                        "fills": int(await conn.fetchval("SELECT COUNT(*) FROM fills")),
                    }

            counts = self._run(_counts())
            self.assertEqual(counts, {"signals": 1, "orders": 1, "fills": 1})

            # Re-processing the same signal must be a no-op (idempotency on signal_id).
            duplicate_fill = self._run(trader_a.process_and_persist(signal))
            self.assertIsNone(duplicate_fill)
            counts_after = self._run(_counts())
            self.assertEqual(counts_after, {"signals": 1, "orders": 1, "fills": 1})
        finally:
            self._run(ctx_a.close())

        # ── Boot #2: fresh portfolio → rehydrate restores everything ────────
        metrics_b = NightwatchMetrics()
        ctx_b = self._run(bootstrap_persistence(self.database_url, metrics=metrics_b))
        try:
            portfolio_b = Portfolio(cash=Decimal("0"), positions={}, last_prices={})
            trader_b = PaperTrader(
                portfolio=portfolio_b,
                order_factory_config=OrderFactoryConfig(order_notional=order_notional),
                fee_model=PercentageFeeModel(rate=fee_rate),
                metrics=metrics_b,
                repos=PaperTraderRepos.from_context(ctx_b),
            )
            self._run(trader_b.rehydrate())

            self.assertEqual(trader_b.portfolio.cash, expected_cash)
            self.assertEqual(trader_b.portfolio.position_qty("BTC/USD"), expected_qty)
            self.assertEqual(trader_b.last_processed_signal_id, expected_signal_id)
        finally:
            self._run(ctx_b.close())


if __name__ == "__main__":
    unittest.main()
