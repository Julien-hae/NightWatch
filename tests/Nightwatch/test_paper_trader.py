"""Unit and integration tests for the PaperTrader paper trading pipeline."""

import json
import unittest
from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from Nightwatch.api import create_app
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


def _extract_json_event(records: list[str], event_name: str) -> dict[str, str]:
    for record in records:
        _, _, payload = record.partition("INFO:Nightwatch.paper_trader:")
        if not payload:
            continue
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if data.get("event") == event_name:
            return data  # type: ignore[no-any-return]
    raise AssertionError(f"event {event_name!r} not found in logs: {records}")


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

    def test_metrics_track_orders_fees_and_equity(self) -> None:
        metrics = NightwatchMetrics()
        portfolio = make_portfolio(cash=Decimal("2000"), last_prices={"BTC/USD": Decimal("50000")})
        trader = _build_paper_trader(portfolio, metrics)
        signal = make_signal(symbol="BTC/USD", side=Side.BUY)

        fill = trader.process_signal(signal)
        assert fill is not None

        self.assertEqual(
            metrics.get_counter_value(metrics.orders_created_total, symbol="BTC/USD", side="BUY"),
            1.0,
        )
        self.assertEqual(
            metrics.get_counter_value(metrics.orders_filled_total, symbol="BTC/USD", side="BUY"),
            1.0,
        )
        self.assertAlmostEqual(
            metrics.get_counter_value(metrics.fees_paid_total, symbol="BTC/USD") or 0.0,
            float(fill.fee),
        )
        self.assertAlmostEqual(metrics.cash_balance._value.get(), float(portfolio.cash))
        self.assertAlmostEqual(
            metrics.position_qty.labels(symbol="BTC/USD")._value.get(),
            float(portfolio.position_qty("BTC/USD")),
        )
        self.assertAlmostEqual(metrics.equity._value.get(), float(portfolio.equity()))
        self.assertAlmostEqual(
            metrics.equity_per_symbol.labels(symbol="BTC/USD")._value.get(),
            float(portfolio.position_qty("BTC/USD") * Decimal("50000")),
        )

    def test_sell_without_position_returns_none(self) -> None:
        portfolio = make_portfolio(cash=Decimal("2000"), last_prices={"BTC/USD": Decimal("50000")})
        trader = _build_paper_trader(portfolio)
        signal = make_signal(symbol="BTC/USD", side=Side.SELL)

        fill = trader.process_signal(signal)

        self.assertIsNone(fill)
        self.assertEqual(portfolio.cash, Decimal("2000"))
        self.assertEqual(portfolio.position_qty("BTC/USD"), Decimal("0"))

    def test_logs_contain_required_keys(self) -> None:
        portfolio = make_portfolio(cash=Decimal("2000"), last_prices={"BTC/USD": Decimal("50000")})
        trader = _build_paper_trader(portfolio)
        signal = make_signal(symbol="BTC/USD", side=Side.BUY)

        with self.assertLogs("Nightwatch.paper_trader", level="INFO") as log:
            fill = trader.process_signal(signal)
        assert fill is not None

        created = _extract_json_event(log.output, "order_created")
        for key in ("order_id", "signal_id", "symbol", "side", "qty", "price"):
            self.assertIn(key, created)

        filled = _extract_json_event(log.output, "order_filled")
        for key in ("order_id", "fill_id", "symbol", "side", "qty", "price", "fee", "cash", "pos", "equity"):
            self.assertIn(key, filled)
        self.assertEqual(filled["order_id"], created["order_id"])
        self.assertEqual(filled["fill_id"], str(fill.fill_id))
        self.assertEqual(filled["cash"], str(portfolio.cash))
        self.assertEqual(filled["pos"], str(portfolio.position_qty("BTC/USD")))
        self.assertEqual(filled["equity"], str(portfolio.equity()))

    def test_observe_price_updates_last_price_and_equity(self) -> None:
        metrics = NightwatchMetrics()
        portfolio = make_portfolio(cash=Decimal("1000"), positions={"BTC/USD": Decimal("0.5")})
        trader = _build_paper_trader(portfolio, metrics)

        trader.observe_price("BTC/USD", Decimal("60000"))

        self.assertEqual(portfolio.last_price("BTC/USD"), Decimal("60000"))
        self.assertAlmostEqual(metrics.equity._value.get(), float(Decimal("1000") + Decimal("0.5") * Decimal("60000")))


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
        self.assertIn("order_created", output)
        self.assertIn("order_filled", output)


class TestMetricsEndpointAfterPaperTrade(unittest.TestCase):
    """Integration test: scrape /metrics after a simulated paper trade."""

    def test_metrics_endpoint_exposes_paper_trading_series(self) -> None:
        metrics = NightwatchMetrics()
        portfolio = make_portfolio(cash=Decimal("2000"), last_prices={"BTC/USD": Decimal("50000")})
        trader = _build_paper_trader(portfolio, metrics)
        trader.process_signal(make_signal(symbol="BTC/USD", side=Side.BUY))

        client = TestClient(create_app(metrics=metrics))
        try:
            response = client.get("/metrics")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        body = response.text
        self.assertIn('orders_created_total{side="BUY",symbol="BTC/USD"} 1.0', body)
        self.assertIn('orders_filled_total{side="BUY",symbol="BTC/USD"} 1.0', body)
        self.assertIn('fees_paid_total{symbol="BTC/USD"}', body)
        self.assertIn('position_qty{symbol="BTC/USD"}', body)
        self.assertIn("cash_balance", body)
        self.assertIn("equity", body)
        self.assertIn('equity_per_symbol{symbol="BTC/USD"}', body)


if __name__ == "__main__":
    unittest.main()
