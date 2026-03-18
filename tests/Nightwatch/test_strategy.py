"""Tests for the Strategy class."""

import unittest
from collections import deque

from Nightwatch.models.market_tick import MarketTick
from Nightwatch.strategies.strategy import Strategy
from tests.fixtures.test_strategy import NoneStrategy


class TestStrategy(unittest.TestCase):
    """Unit tests for the Strategy class."""

    def test_cannot_instantiate_directly(self) -> None:
        """Given Strategy is abstract, When instantiated, Then TypeError."""
        with self.assertRaises(TypeError):
            Strategy()  # type: ignore[abstract]

    def test_on_tick_returns_none(self) -> None:
        """Given a concrete implementation of Strategy, When on_tick is called, Then it returns None."""
        strategy = NoneStrategy()
        symbol = "TEST-SYMBOL"
        window: deque[MarketTick] = deque()
        self.assertIsNone(strategy.on_tick(symbol, window))
