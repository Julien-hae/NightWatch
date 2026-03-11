# mypy: disable-error-code="import-untyped"
"""Unit tests for the TickBuffer class in Nightwatch."""

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from Nightwatch.models.market_tick import MarketTick
from Nightwatch.models.tick_buffer import TickBuffer


class TestTickBuffer(unittest.TestCase):
    """Test suite for the RollingTickBuffer."""

    buffer: TickBuffer

    def setUp(self) -> None:
        """Set up a new TickBuffer for each test."""
        self.buffer = TickBuffer()

    def test_given_buffer_of_3_when_4_ticks_added_then_oldest_evicted(self) -> None:
        """Test that when more than max_ticks_per_symbol are added, the oldest tick is evicted from the buffer."""
        self.buffer = TickBuffer(max_ticks_per_symbol=3)
        for i in range(4):
            tick = MarketTick(
                symbol="BTC/USD", price=Decimal(str(i)), timestamp=datetime.now(timezone.utc), source="test", schema_version=1
            )
            self.buffer.add_tick(tick)
        self.assertEqual(len(self.buffer.ticks["BTC/USD"]), 3)
        self.assertEqual(self.buffer.ticks["BTC/USD"][0].price, Decimal("1"))  # oldest evicted

    def test_given_two_symbols_when_ticks_added_then_isolated(self) -> None:
        """Test that ticks for different symbols are stored in separate buffers and do not interfere with each other."""
        btc_tick = MarketTick(symbol="BTC/USD", price=Decimal("0"), timestamp=datetime.now(timezone.utc), source="test", schema_version=1)
        eth_tick = MarketTick(symbol="ETH/USD", price=Decimal("0"), timestamp=datetime.now(timezone.utc), source="test", schema_version=1)
        self.buffer.add_tick(btc_tick)
        self.buffer.add_tick(eth_tick)
        self.assertIn("BTC/USD", self.buffer.ticks)
        self.assertIn("ETH/USD", self.buffer.ticks)

    def test_given_empty_buffer_when_read_then_empty_dict(self) -> None:
        """Test that a newly initialized TickBuffer has an empty ticks dictionary."""
        buf = TickBuffer()
        self.assertEqual(len(buf.ticks), 0)

    def test_order_preserved(self) -> None:
        """Test that the order of ticks is preserved in the buffer."""
        buf = TickBuffer(max_ticks_per_symbol=5)
        timestamps = [datetime(2024, 1, 1, i, tzinfo=timezone.utc) for i in range(5)]
        for ts in timestamps:
            tick = MarketTick(symbol="BTC/USD", price=Decimal("0"), timestamp=ts, source="test", schema_version=1)
            buf.add_tick(tick)
        stored = list(buf.ticks["BTC/USD"])
        self.assertEqual([t.timestamp for t in stored], timestamps)
