"""Unit and integration tests for the PaperTrader paper trading pipeline."""

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from Nightwatch.metrics import NightwatchMetrics
from Nightwatch.models.order_factory import OrderFactoryConfig
from Nightwatch.models.paper_execution import PercentageFeeModel
from Nightwatch.models.portfolio import Portfolio
from Nightwatch.models.signal import Side
from Nightwatch.models.tick_buffer import TickBuffer
from Nightwatch.paper_trader import PaperTrader
from Nightwatch.risk_engine import RiskEngine
from Nightwatch.rules.max_signal_per_minute_rule import MaxSignalPerMinuteRule
from Nightwatch.strategies.momentum_burst import MomentumBurstStrategy
from Nightwatch.strategy_runner import StrategyRunner
from tests.fixtures.portfolio_factory import make_portfolio
from tests.fixtures.signal_factory import make_signal
from tests.fixtures.tick_factory import feed_ticks, make_tick_sequence


def _build_paper_trader(portfolio: Portfolio, metrics: NightwatchMetrics | None = None) -> PaperTrader:
    return PaperTrader(
        portfolio=portfolio,
        order_factory_config=OrderFactoryConfig(order_notional=Decimal("100")),
        fee_model=PercentageFeeModel(rate=Decimal("0.001")),
        metrics=metrics,
    )


class TestPaperTraderProcessSignal(unittest.TestCase):
    def test_buy_signal_produces_fill_and_updates_portfolio(self) -> None:
        metrics = NightwatchMetrics()
        portfolio = make_portfolio(cash=Decimal("2000"), last_prices={"BTC/USD": Decimal("50000")})
        trader = _build_paper_trader(portfolio, metrics)
        signal = make_signal(symbol="BTC/USD", side=Side.BUY)

        fill = trader.process_signal(signal)

        self.assertIsNotNone(fill)
        assert fill is not None
        expected_qty = Decimal("100") / Decimal("50000")
        self.assertEqual(fill.qty, expected_qty)
        self.assertEqual(fill.price, Decimal("50000"))
        self.assertEqual(fill.fee, expected_qty * Decimal("50000") * Decimal("0.001"))
        self.assertEqual(portfolio.position_qty("BTC/USD"), expected_qty)
        self.assertEqual(portfolio.cash, Decimal("2000") - Decimal("100") - fill.fee)

    def test_duplicate_signal_is_ignored(self) -> None:
        portfolio = make_portfolio(cash=Decimal("2000"), last_prices={"BTC/USD": Decimal("50000")})
        trader = _build_paper_trader(portfolio)
        signal = make_signal(symbol="BTC/USD", side=Side.BUY)

        first = trader.process_signal(signal)
        second = trader.process_signal(signal)

        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_metrics_track_orders_and_equity(self) -> None:
        metrics = NightwatchMetrics()
        portfolio = make_portfolio(cash=Decimal("2000"), last_prices={"BTC/USD": Decimal("50000")})
        trader = _build_paper_trader(portfolio, metrics)
        signal = make_signal(symbol="BTC/USD", side=Side.BUY)

        trader.process_signal(signal)

        self.assertEqual(
            metrics.get_counter_value(metrics.orders_created_total, symbol="BTC/USD", side="BUY"),
            1.0,
        )
        self.assertEqual(
            metrics.get_counter_value(metrics.orders_filled_total, symbol="BTC/USD", side="BUY"),
            1.0,
        )
        self.assertAlmostEqual(metrics.portfolio_cash._value.get(), float(portfolio.cash))
        self.assertAlmostEqual(metrics.portfolio_equity._value.get(), float(portfolio.equity()))

    def test_sell_without_position_returns_none(self) -> None:
        portfolio = make_portfolio(cash=Decimal("2000"), last_prices={"BTC/USD": Decimal("50000")})
        trader = _build_paper_trader(portfolio)
        signal = make_signal(symbol="BTC/USD", side=Side.SELL)

        fill = trader.process_signal(signal)

        self.assertIsNone(fill)
        self.assertEqual(portfolio.cash, Decimal("2000"))
        self.assertEqual(portfolio.position_qty("BTC/USD"), Decimal("0"))

    def test_logs_emit_order_created_and_filled(self) -> None:
        portfolio = make_portfolio(cash=Decimal("2000"), last_prices={"BTC/USD": Decimal("50000")})
        trader = _build_paper_trader(portfolio)
        signal = make_signal(symbol="BTC/USD", side=Side.BUY)

        with self.assertLogs("Nightwatch.paper_trader", level="INFO") as log:
            trader.process_signal(signal)

        output = "\n".join(log.output)
        self.assertIn("ORDER_CREATED", output)
        self.assertIn("ORDER_FILLED", output)

    def test_observe_price_updates_last_price_and_equity(self) -> None:
        metrics = NightwatchMetrics()
        portfolio = make_portfolio(cash=Decimal("1000"), positions={"BTC/USD": Decimal("0.5")})
        trader = _build_paper_trader(portfolio, metrics)

        trader.observe_price("BTC/USD", Decimal("60000"))

        self.assertEqual(portfolio.last_price("BTC/USD"), Decimal("60000"))
        self.assertAlmostEqual(metrics.portfolio_equity._value.get(), float(Decimal("1000") + Decimal("0.5") * Decimal("60000")))


class TestStrategyRunnerPaperTradingPipeline(unittest.TestCase):
    """End-to-end pipeline test: synthetic ticks -> approved signal -> fill -> portfolio update."""

    def test_buy_signal_flows_through_pipeline(self) -> None:
        metrics = NightwatchMetrics()
        strategy = MomentumBurstStrategy(threshold_pct=10, metric=metrics)
        buffer = TickBuffer(max_ticks_per_symbol=30)
        risk_engine = RiskEngine(rules=[MaxSignalPerMinuteRule(max_signals_per_min=1000)])
        portfolio = Portfolio(cash=Decimal("2000"))
        trader = _build_paper_trader(portfolio, metrics)
        runner = StrategyRunner(
            strategy=strategy,
            buffer=buffer,
            metric=metrics,
            risk_engine=risk_engine,
            paper_trader=trader,
        )

        starting_cash = portfolio.cash
        ticks = make_tick_sequence(
            prices=[Decimal("100"), Decimal("105"), Decimal("115")],
            start=datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            interval_sec=5.0,
            symbol="BTC/USD",
        )

        with self.assertLogs("Nightwatch.paper_trader", level="INFO") as log:
            signal = feed_ticks(runner, ticks)

        self.assertIsNotNone(signal)
        self.assertEqual(
            metrics.get_counter_value(metrics.orders_created_total, symbol="BTC/USD", side="BUY"),
            1.0,
        )
        self.assertEqual(
            metrics.get_counter_value(metrics.orders_filled_total, symbol="BTC/USD", side="BUY"),
            1.0,
        )
        self.assertGreater(portfolio.position_qty("BTC/USD"), Decimal("0"))
        self.assertLess(portfolio.cash, starting_cash)
        output = "\n".join(log.output)
        self.assertIn("ORDER_CREATED", output)
        self.assertIn("ORDER_FILLED", output)


if __name__ == "__main__":
    unittest.main()
