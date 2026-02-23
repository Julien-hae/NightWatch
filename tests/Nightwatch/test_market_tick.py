"""Test for the MarketTick model."""

import unittest
import uuid
from datetime import datetime

from Nightwatch.models.market_tick import MarketTick


class TestMarketTick(unittest.TestCase):
    """Unit tests for the MarketTick model."""

    def setUp(self) -> None:
        """Set up the MarketTick instance for testing."""
        self.market_tick = MarketTick(symbol="BTC/USD", price=50000.0, timestamp=datetime.now(), source="Kraken", schema_version=1)  # type: ignore[arg-type]

    def test_market_tick_fields(self) -> None:
        """Test that the MarketTick fields are set correctly."""
        self.assertEqual(self.market_tick.symbol, "BTC/USD")
        self.assertEqual(self.market_tick.price, 50000.0)
        self.assertEqual(self.market_tick.source, "Kraken")
        self.assertEqual(self.market_tick.schema_version, 1)
        self.assertIsInstance(self.market_tick.timestamp, datetime)
        self.assertIsInstance(self.market_tick.uid, uuid.UUID)

    def test_json_serialization(self) -> None:
        """Test that the MarketTick can be serialized to JSON."""
        market_tick_json = self.market_tick.model_dump()
        self.assertIsInstance(market_tick_json, dict)
        self.assertIn("uid", market_tick_json)
        self.assertIn("timestamp", market_tick_json)
        self.assertIn("symbol", market_tick_json)
        self.assertIn("price", market_tick_json)
        self.assertIn("source", market_tick_json)
        self.assertIn("schema_version", market_tick_json)

    def test_negative_price(self) -> None:
        """Test that a negative price raises a validation error."""
        with self.assertRaises(ValueError):
            MarketTick(symbol="BTC/USD", price=-100.0, timestamp=datetime.now(), source="Kraken", schema_version=1)  # type: ignore[arg-type]

    def test_missing_fields(self) -> None:
        """Test that missing required fields raise a validation error."""
        with self.assertRaises(ValueError):
            MarketTick(timestamp=datetime.now(), source="Kraken", schema_version=1)  # type: ignore[call-arg]
