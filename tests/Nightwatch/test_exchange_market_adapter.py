"""Tests for the ExchangeMarketAdapter class."""

import unittest

from Nightwatch.exchange_market_adapter import ExchangeMarketAdapter, MarketTick


class TestExchangeMarketAdapter(unittest.TestCase):
    """Unit tests for the ExchangeMarketAdapter class."""

    def test_method_connect(self) -> None:
        """Test the connect method of the ExchangeMarketAdapter class."""
        adapter = ExchangeMarketAdapter()
        self.assertTrue(callable(getattr(adapter, "connect", None)))

    def test_method_subscribe(self) -> None:
        """Test the subscribe method of the ExchangeMarketAdapter class."""
        adapter = ExchangeMarketAdapter()
        self.assertTrue(callable(getattr(adapter, "subscribe", None)))

    def test_method_parse_message(self) -> None:
        """Test the parse_message method of the ExchangeMarketAdapter class."""
        adapter = ExchangeMarketAdapter()
        self.assertTrue(callable(getattr(adapter, "parse_message", None)))

    def test_return_value_parse_message(self) -> None:
        """Test the return value of the parse_message method of the ExchangeMarketAdapter class."""
        adapter = ExchangeMarketAdapter()
        market_tick = adapter.parse_message(message=None)
        self.assertIsInstance(market_tick, MarketTick)
