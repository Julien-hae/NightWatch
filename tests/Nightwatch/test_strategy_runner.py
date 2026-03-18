"""Unit tests for the StrategyRunner class."""

import unittest
from collections import deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from Nightwatch.models.tick_buffer import TickBuffer
from Nightwatch.strategies.momentum_burst import MomentumBurstStrategy
from Nightwatch.strategy_runner import StrategyRunner
from tests.fixtures.tick_factory import make_tick


class TestStrategyRunner(unittest.TestCase):
    """Unit tests for the StrategyRunner class."""

    def setUp(self) -> None:
        self.__strategy = MomentumBurstStrategy(threshold_pct=10)
        self.__buffer = TickBuffer(max_ticks_per_symbol=30)
        self.runner = StrategyRunner(strategy=self.__strategy, buffer=self.__buffer, cooldown=10)
        self.start_time = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)

    def test_emit_signal_on_rising_sequence(self) -> None:
        """Test that a rising sequence of ticks generates a buy signal."""
        signal = None
        i = 0
        rising_ticks = deque(
            [
                make_tick(price=Decimal("100"), timestamp=self.start_time),
                make_tick(price=Decimal("105"), timestamp=self.start_time + timedelta(seconds=5)),
                make_tick(price=Decimal("115"), timestamp=self.start_time + timedelta(seconds=10)),
            ]
        )
        while signal is None and i < len(rising_ticks):
            tick = rising_ticks[i]
            signal = self.runner.on_market_tick(tick)
            i += 1
        self.assertIsNotNone(signal)
        self.assertEqual(signal.side, "BUY")  # type: ignore[union-attr]

    def test_emit_no_signal_on_falling_sequence(self) -> None:
        """Test that an outside threshold sequence of ticks does not generate a signal."""
        signal = None
        i = 0
        failing_ticks = deque(
            [
                make_tick(price=Decimal("100"), timestamp=self.start_time),
                make_tick(price=Decimal("95"), timestamp=self.start_time + timedelta(seconds=5)),
                make_tick(price=Decimal("105"), timestamp=self.start_time + timedelta(seconds=10)),
            ]
        )
        while signal is None and i < len(failing_ticks):
            tick = failing_ticks[i]
            signal = self.runner.on_market_tick(tick)
            i += 1
        self.assertIsNone(signal)

    def test_cooldown_prevents_signal(self) -> None:
        """Test that the cooldown period prevents emitting signals too frequently."""
        signal = None
        i = 0
        ticks = deque(
            [
                make_tick(price=Decimal("100"), timestamp=self.start_time),
                make_tick(price=Decimal("105"), timestamp=self.start_time + timedelta(seconds=5)),
                make_tick(price=Decimal("115"), timestamp=self.start_time + timedelta(seconds=10)),
                make_tick(price=Decimal("120"), timestamp=self.start_time + timedelta(seconds=15)),
            ]
        )
        while signal is None and i < len(ticks):
            tick = ticks[i]
            signal = self.runner.on_market_tick(tick)
            i += 1
        self.assertIsNotNone(signal)
        self.assertEqual(signal.side, "BUY")  # type: ignore[union-attr]

        # Now we are in cooldown, the next tick should not generate a signal
        next_tick = make_tick(price=Decimal("125"), timestamp=self.start_time + timedelta(seconds=20))
        signal = self.runner.on_market_tick(next_tick)
        self.assertIsNone(signal)

    def test_integration_with_momentum_burst_strategy(self) -> None:
        """Test that the StrategyRunner correctly integrates with the MomentumBurstStrategy."""
        signal = None
        i = 0
        ticks = deque(
            [
                make_tick(price=Decimal("100"), timestamp=self.start_time),
                make_tick(price=Decimal("105"), timestamp=self.start_time + timedelta(seconds=5)),
                make_tick(price=Decimal("115"), timestamp=self.start_time + timedelta(seconds=10)),
            ]
        )
        while signal is None and i < len(ticks):
            tick = ticks[i]
            signal = self.runner.on_market_tick(tick)
            i += 1
        self.assertIsNotNone(signal)
        self.assertEqual(signal.side, "BUY")  # type: ignore[union-attr]
