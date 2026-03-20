# mypy: disable-error-code="import-untyped, union-attr"
"""Unit tests for the StrategyRunner class."""

import unittest
from collections import deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from Nightwatch.metrics import NightwatchMetrics
from Nightwatch.models.tick_buffer import TickBuffer
from Nightwatch.strategies.momentum_burst import MomentumBurstStrategy
from Nightwatch.strategy_runner import StrategyRunner
from tests.fixtures.tick_factory import feed_ticks, make_tick


class TestStrategyRunner(unittest.TestCase):
    """Unit tests for the StrategyRunner class."""

    def setUp(self) -> None:
        self._metric = NightwatchMetrics()
        self.__strategy = MomentumBurstStrategy(threshold_pct=10, metric=self._metric)
        self.__buffer = TickBuffer(max_ticks_per_symbol=30)
        self.runner = StrategyRunner(strategy=self.__strategy, buffer=self.__buffer, cooldown=timedelta(seconds=10), metric=self._metric)
        self.start_time = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)

    def test_emit_signal_on_rising_sequence(self) -> None:
        """Test that a rising sequence of ticks generates a buy signal."""
        rising_ticks = deque(
            [
                make_tick(price=Decimal("100"), timestamp=self.start_time),
                make_tick(price=Decimal("105"), timestamp=self.start_time + timedelta(seconds=5)),
                make_tick(price=Decimal("115"), timestamp=self.start_time + timedelta(seconds=10)),
            ]
        )
        signal = feed_ticks(self.runner, rising_ticks)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.side, "BUY")  # type: ignore[union-attr]

    def test_emit_no_signal_on_falling_sequence(self) -> None:
        """Test that an outside threshold sequence of ticks does not generate a signal."""
        failing_ticks = deque(
            [
                make_tick(price=Decimal("100"), timestamp=self.start_time),
                make_tick(price=Decimal("95"), timestamp=self.start_time + timedelta(seconds=5)),
                make_tick(price=Decimal("105"), timestamp=self.start_time + timedelta(seconds=10)),
            ]
        )
        signal = feed_ticks(self.runner, failing_ticks)
        self.assertIsNone(signal)

    def test_cooldown_prevents_signal(self) -> None:
        """Test that the cooldown period prevents emitting signals too frequently."""
        strategy_no_cd = MomentumBurstStrategy(threshold_pct=1, window_sec=60, metric=self._metric)
        buffer_no_cd = TickBuffer(max_ticks_per_symbol=30)
        runner_no_cd = StrategyRunner(strategy=strategy_no_cd, buffer=buffer_no_cd)

        ticks = deque(
            [
                make_tick(price=Decimal("100"), timestamp=self.start_time),
                make_tick(price=Decimal("105"), timestamp=self.start_time + timedelta(seconds=5)),
                make_tick(price=Decimal("115"), timestamp=self.start_time + timedelta(seconds=10)),
            ]
        )

        signal = feed_ticks(runner_no_cd, ticks)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.side, "BUY")  # type: ignore[union-attr]

        next_tick = make_tick(price=Decimal("130"), timestamp=self.start_time + timedelta(seconds=11))
        second_signal_no_cd = runner_no_cd.on_market_tick(next_tick)
        self.assertIsNotNone(second_signal_no_cd)
        self.assertEqual(second_signal_no_cd.side, "BUY")

        strategy_cd = MomentumBurstStrategy(threshold_pct=1, window_sec=60, metric=self._metric)
        buffer_cd = TickBuffer(max_ticks_per_symbol=30)
        runner_cd = StrategyRunner(strategy=strategy_cd, buffer=buffer_cd, cooldown=timedelta(seconds=10))

        signal = None
        i = 0
        while signal is None and i < len(ticks):
            tick = ticks[i]
            signal = runner_cd.on_market_tick(tick)
            i += 1
        self.assertIsNotNone(signal)
        self.assertEqual(signal.side, "BUY")  # type: ignore[union-attr]

        signal_during_cooldown = runner_cd.on_market_tick(next_tick)
        self.assertIsNone(signal_during_cooldown)

    def test_cooldown_increments_suppressed_metric(self) -> None:
        """Given a signal was just emitted, when the next tick arrives within cooldown,
        then signals_suppressed_total{reason='cooldown'} increments by 1."""
        ticks = [
            make_tick(price=Decimal("100"), timestamp=self.start_time),
            make_tick(price=Decimal("105"), timestamp=self.start_time + timedelta(seconds=5)),
            make_tick(price=Decimal("115"), timestamp=self.start_time + timedelta(seconds=10)),
        ]
        for tick in ticks:
            self.runner.on_market_tick(tick)
        suppressed_tick = make_tick(
            price=Decimal("130"),
            timestamp=self.start_time + timedelta(seconds=15),
        )
        result = self.runner.on_market_tick(suppressed_tick)

        self.assertIsNone(result)
        # THIS is the new assertion — the metric must reflect the suppression
        value = self._metric.get_counter_value(self._metric.signals_suppressed_total, reason="cooldown")
        self.assertEqual(value, 1.0)

    def test_integration_with_momentum_burst_strategy(self) -> None:
        """Test that the StrategyRunner correctly integrates with the MomentumBurstStrategy."""

        ticks = deque(
            [
                make_tick(price=Decimal("100"), timestamp=self.start_time),
                make_tick(price=Decimal("105"), timestamp=self.start_time + timedelta(seconds=5)),
                make_tick(price=Decimal("115"), timestamp=self.start_time + timedelta(seconds=10)),
            ]
        )
        signal = feed_ticks(self.runner, ticks)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.side, "BUY")  # type: ignore[union-attr]

    def test_logging_contains_required_fields(self) -> None:
        """Test that the logs contain the required fields when emitting signals."""
        with self.assertLogs("Nightwatch.strategy_runner", level="DEBUG") as log:
            ticks = deque(
                [
                    make_tick(price=Decimal("100"), timestamp=self.start_time),
                    make_tick(price=Decimal("105"), timestamp=self.start_time + timedelta(seconds=5)),
                    make_tick(price=Decimal("115"), timestamp=self.start_time + timedelta(seconds=10)),
                ]
            )
            for tick in ticks:
                self.runner.on_market_tick(tick)

        log_output = "\n".join(log.output)
        self.assertIn("event", log_output)
        self.assertIn("signal_id", log_output)
        self.assertIn("symbol", log_output)
        self.assertIn("side", log_output)
        self.assertIn("strategy", log_output)
        self.assertIn("delta_pct", log_output)
        self.assertIn("window_sec", log_output)
        self.assertIn("threshold_pct", log_output)

    def test_cooldown_per_symbol(self) -> None:
        """Test that the cooldown is applied separately for each symbol."""
        metric = NightwatchMetrics()
        strategy = MomentumBurstStrategy(threshold_pct=10, metric=metric)
        buffer = TickBuffer(max_ticks_per_symbol=30)
        runner = StrategyRunner(strategy=strategy, buffer=buffer, cooldown=timedelta(seconds=30), metric=metric)
        ticks_symbol = deque(
            [
                make_tick(price=Decimal("100"), timestamp=self.start_time, symbol="A"),
                make_tick(price=Decimal("100"), timestamp=self.start_time, symbol="B"),
                make_tick(price=Decimal("105"), timestamp=self.start_time + timedelta(seconds=5), symbol="A"),
                make_tick(price=Decimal("105"), timestamp=self.start_time + timedelta(seconds=5), symbol="B"),
                make_tick(price=Decimal("115"), timestamp=self.start_time + timedelta(seconds=10), symbol="A"),
                make_tick(price=Decimal("115"), timestamp=self.start_time + timedelta(seconds=10), symbol="B"),
                make_tick(price=Decimal("130"), timestamp=self.start_time + timedelta(seconds=15), symbol="A"),
                make_tick(price=Decimal("130"), timestamp=self.start_time + timedelta(seconds=45), symbol="B"),
            ]
        )
        signal_a = None
        signal_b = None
        for tick in ticks_symbol:
            result = runner.on_market_tick(tick)
            if tick.symbol == "A" and signal_a is None and result is not None:
                signal_a = result
            elif tick.symbol == "B" and signal_b is None and result is not None:
                signal_b = result

        self.assertIsNotNone(signal_a)
        self.assertIsNotNone(signal_b)
        self.assertEqual(signal_a.side, "BUY")  # type: ignore[union-attr]
        self.assertEqual(signal_b.side, "BUY")  # type: ignore[union-attr]
        self.assertEqual(runner.get_suppressed_signal_totals(reason="cooldown"), 1.0)

    def test_signals_total(self) -> None:
        """Test that the counter signals_total is incremented correctly."""
        initial_evaluations = (
            self._metric.get_counter_value(self._metric.signals_total, symbol="BTC/USD", side="BUY", strategy=self.__strategy.NAME) or 0
        )
        ticks = deque(
            [
                make_tick(price=Decimal("100"), timestamp=self.start_time),
                make_tick(price=Decimal("115"), timestamp=self.start_time + timedelta(seconds=10)),
                make_tick(price=Decimal("135"), timestamp=self.start_time + timedelta(seconds=20)),
            ]
        )
        feed_ticks(self.runner, ticks)
        final_evaluations = (
            self._metric.get_counter_value(self._metric.signals_total, symbol="BTC/USD", side="BUY", strategy=self.__strategy.NAME) or 0
        )
        self.assertEqual(final_evaluations, initial_evaluations + 1)

    def test_cooldown_zero_does_not_suppress_same_timestamp(self) -> None:
        """Given cooldown=0, when two qualifying ticks arrive at the same timestamp,
        then both emit signals (no suppression)."""
        strategy = MomentumBurstStrategy(threshold_pct=10, metric=self._metric)
        buffer = TickBuffer(max_ticks_per_symbol=30)
        runner = StrategyRunner(strategy=strategy, buffer=buffer, cooldown=timedelta(seconds=0), metric=self._metric)

        ticks = deque(
            [
                make_tick(price=Decimal("100"), timestamp=self.start_time),
                make_tick(price=Decimal("115"), timestamp=self.start_time + timedelta(seconds=10)),
            ]
        )
        signal1 = feed_ticks(runner, ticks)
        self.assertIsNotNone(signal1)

        # Same timestamp, still qualifying
        tick_at_boundary = make_tick(price=Decimal("135"), timestamp=self.start_time + timedelta(seconds=10))
        signal2 = runner.on_market_tick(tick_at_boundary)
        self.assertIsNotNone(signal2)  # Should NOT be suppressed with cooldown=0

    def test_access_private_last_signal_time(self) -> None:
        """Test that we can access the private _last_signal_time attribute for testing purposes."""
        self.assertIsInstance(self.runner._last_signal_time, dict)
