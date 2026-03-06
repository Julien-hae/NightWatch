"""Tests for the ExchangeMarketAdapter class."""

import unittest

from Nightwatch.exchange_market_adapter import ExchangeMarketAdapter


class TestExchangeMarketAdapter(unittest.TestCase):
    """Unit tests for the ExchangeMarketAdapter class."""

    def test_cannot_instantiate_directly(self) -> None:
        """Given ExchangeMarketAdapter is abstract, When instantiated, Then TypeError."""
        with self.assertRaises(TypeError):
            ExchangeMarketAdapter()  # type: ignore
