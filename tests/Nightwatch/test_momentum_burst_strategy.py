"""Simple unit tests for the MomentumBurstStrategy class."""

import unittest
from collections import deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from Nightwatch.metrics import NightwatchMetrics
from Nightwatch.strategies.momentum_burst import MomentumBurstStrategy
from tests.fixtures.tick_factory import make_tick


class TestMomentumBurstStrategy(unittest.TestCase):
    """Unit tests for the MomentumBurstStrategy class."""

    def setUp(self) -> None:
        """Set up the test case with an instance of MomentumBurstStrategy."""
        self._metric = NightwatchMetrics()
        self.strategy = MomentumBurstStrategy(window_sec=10.0, threshold_pct=10, metric=self._metric)
        self.start_time = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)

    def test_rising_seq_crosses_threshold(self) -> None:
        """Test that a rising sequence of ticks crossing the threshold generates a buy signal."""

        ticks = deque(
            [
                make_tick(price=Decimal("100"), timestamp=self.start_time),
                make_tick(price=Decimal("105"), timestamp=self.start_time + timedelta(seconds=5)),
                make_tick(price=Decimal("115"), timestamp=self.start_time + timedelta(seconds=10)),
            ]
        )
        signal = self.strategy.on_tick(ticks[-1].symbol, ticks)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.side.value, "BUY")  # type: ignore[union-attr]

    def test_falling_seq_crosses_threshold(self) -> None:
        """Test that a falling sequence of ticks crossing the threshold generates a sell signal."""

        ticks = deque(
            [
                make_tick(price=Decimal("100"), timestamp=self.start_time),
                make_tick(price=Decimal("95"), timestamp=self.start_time + timedelta(seconds=5)),
                make_tick(price=Decimal("85"), timestamp=self.start_time + timedelta(seconds=10)),
            ]
        )
        signal = self.strategy.on_tick(ticks[-1].symbol, ticks)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.side.value, "SELL")  # type: ignore[union-attr]

    def test_noise_under_thresholds(self) -> None:
        """Test that noisy sequences outside thresholds generate a None signal."""

        ticks = deque(
            [
                make_tick(price=Decimal("100"), timestamp=self.start_time),
                make_tick(price=Decimal("95"), timestamp=self.start_time + timedelta(seconds=5)),
                make_tick(price=Decimal("105"), timestamp=self.start_time + timedelta(seconds=10)),
            ]
        )
        signal = self.strategy.on_tick(ticks[-1].symbol, ticks)
        self.assertIsNone(signal)

    def test_not_enough_ticks_in_window(self) -> None:
        """Test that sequences with not enough ticks in the window generate a None signal."""

        ticks = deque(
            [
                make_tick(price=Decimal("100"), timestamp=self.start_time),
            ]
        )
        signal = self.strategy.on_tick(ticks[-1].symbol, ticks)
        self.assertIsNone(signal)

    def test_no_ticks_in_window(self) -> None:
        """Test that an empty window generates a None signal."""
        signal = self.strategy.on_tick("TEST", deque())
        self.assertIsNone(signal)

    def test_start_price_is_zero(self) -> None:
        """Test that a sequence starting with a price of zero generates a None signal."""
        ticks = deque(
            [
                make_tick(price=Decimal("0"), timestamp=self.start_time),
                make_tick(price=Decimal("5"), timestamp=self.start_time + timedelta(seconds=5)),
                make_tick(price=Decimal("10"), timestamp=self.start_time + timedelta(seconds=10)),
            ]
        )
        signal = self.strategy.on_tick(ticks[-1].symbol, ticks)
        self.assertIsNone(signal)

    def test_exactly_at_threshold(self) -> None:
        """Test that a sequence that is exactly at the threshold generates a buy signal."""
        ticks = deque(
            [
                make_tick(price=Decimal("100"), timestamp=self.start_time),
                make_tick(price=Decimal("105"), timestamp=self.start_time + timedelta(seconds=5)),
                make_tick(price=Decimal("110"), timestamp=self.start_time + timedelta(seconds=10)),
            ]
        )
        signal = self.strategy.on_tick(ticks[-1].symbol, ticks)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.side.value, "BUY")  # type: ignore[union-attr]

    def test_just_below_threshold(self) -> None:
        """Test that a sequence that is just below the threshold generates a None signal."""

        ticks = deque(
            [
                make_tick(price=Decimal("100"), timestamp=self.start_time),
                make_tick(price=Decimal("105"), timestamp=self.start_time + timedelta(seconds=5)),
                make_tick(price=Decimal("109.99"), timestamp=self.start_time + timedelta(seconds=10)),
            ]
        )
        signal = self.strategy.on_tick(ticks[-1].symbol, ticks)
        self.assertIsNone(signal)

    def test_within_time_window(self) -> None:
        """Test that a sequence with ticks outside the time window generates a None signal."""

        ticks = deque(
            [
                make_tick(price=Decimal("100"), timestamp=self.start_time),
                make_tick(price=Decimal("105"), timestamp=self.start_time + timedelta(seconds=15)),
                make_tick(price=Decimal("115"), timestamp=self.start_time + timedelta(seconds=20)),
            ]
        )
        signal = self.strategy.on_tick(ticks[-1].symbol, ticks)
        self.assertIsNone(signal)

    def test_strategy_evaluations_total(self) -> None:
        """Test that the counter strategy_evaluations_total is incremented correctly."""
        initial_evaluations = self.strategy.get_strategy_evaluations_total(symbol="BTC/USD", strategy=self.strategy.NAME) or 0
        ticks = deque(
            [
                make_tick(price=Decimal("100"), timestamp=self.start_time),
                make_tick(price=Decimal("105"), timestamp=self.start_time + timedelta(seconds=5)),
                make_tick(price=Decimal("115"), timestamp=self.start_time + timedelta(seconds=10)),
            ]
        )
        self.strategy.on_tick(ticks[-1].symbol, ticks)
        self.assertEqual(
            self.strategy.get_strategy_evaluations_total(symbol="BTC/USD", strategy=self.strategy.NAME), initial_evaluations + 1
        )

    def test_invalid_parameters(self) -> None:
        """Test that invalid parameters raise ValueError."""
        with self.assertRaises(ValueError):
            MomentumBurstStrategy(window_sec=-10, threshold_pct=10)
        with self.assertRaises(ValueError):
            MomentumBurstStrategy(window_sec=10, threshold_pct=-10)

    def test_determinism_same_ticks_yield_same_signals(self) -> None:
        """Given the same tick sequence replayed twice, then emitted signals are identical."""
        ticks = deque(
            [
                make_tick(price=Decimal("100"), timestamp=self.start_time),
                make_tick(price=Decimal("105"), timestamp=self.start_time + timedelta(seconds=5)),
                make_tick(price=Decimal("115"), timestamp=self.start_time + timedelta(seconds=10)),
            ]
        )

        signals_run1 = [self.strategy.on_tick(t.symbol, deque(list(ticks)[: i + 1])) for i, t in enumerate(ticks)]

        strategy2 = MomentumBurstStrategy(window_sec=10.0, threshold_pct=10)
        signals_run2 = [strategy2.on_tick(t.symbol, deque(list(ticks)[: i + 1])) for i, t in enumerate(ticks)]

        for s1, s2 in zip(signals_run1, signals_run2):
            if s1 is None:
                self.assertIsNone(s2)
            else:
                self.assertEqual(s1.side, s2.side)  # type: ignore[union-attr]
                self.assertEqual(s1.strength, s2.strength)  # type: ignore[union-attr]

    def test_all_ticks_same_timestamp_no_signal(self) -> None:
        """Given all ticks have identical timestamps and different prices,
        when evaluated, then no signal is emitted because the price move
        happened in zero elapsed real time (delta_pct = 5%, but it's noise)."""
        t = self.start_time
        ticks = deque(
            [
                make_tick(price=Decimal("100"), timestamp=t),
                make_tick(price=Decimal("105"), timestamp=t),
                make_tick(price=Decimal("115"), timestamp=t),
            ]
        )
        signal = self.strategy.on_tick(ticks[-1].symbol, ticks)
        self.assertIsNone(signal)
