# mypy: disable-error-code="import-untyped"
"""Unit tests for the TickBuffer class in Nightwatch."""

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from Nightwatch.models.tick_buffer import TickBuffer
from tests.fixtures.tick_factory import make_tick


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
            tick = make_tick(price=Decimal(str(i)))
            self.buffer.add_tick(tick)
        self.assertEqual(len(self.buffer.get_ticks("BTC/USD")), 3)
        self.assertEqual(self.buffer.get_ticks("BTC/USD")[0].price, Decimal("1"))  # oldest evicted

    def test_given_two_symbols_when_ticks_added_then_isolated(self) -> None:
        """Test that ticks for different symbols are stored in separate buffers and do not interfere with each other."""
        btc_tick = make_tick(symbol="BTC/USD")
        eth_tick = make_tick(symbol="ETH/USD")
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
            tick = make_tick(symbol="BTC/USD", timestamp=ts)
            buf.add_tick(tick)
        stored = list(buf.get_ticks("BTC/USD"))
        self.assertEqual([t.timestamp for t in stored], timestamps)

    def test_out_of_order_tick_discarded(self) -> None:
        """Test that a tick with an earlier timestamp than the latest stored tick is discarded."""
        buf = TickBuffer(max_ticks_per_symbol=5)
        t0 = datetime(2024, 1, 1, 0, tzinfo=timezone.utc)
        t1 = datetime(2024, 1, 1, 1, tzinfo=timezone.utc)
        t_late = datetime(2024, 1, 1, 0, 30, tzinfo=timezone.utc)
        buf.add_tick(make_tick(symbol="BTC/USD", timestamp=t0))
        buf.add_tick(make_tick(symbol="BTC/USD", timestamp=t1))
        buf.add_tick(make_tick(symbol="BTC/USD", timestamp=t_late))
        stored = list(buf.get_ticks("BTC/USD"))
        self.assertEqual(len(stored), 2)
        self.assertEqual([t.timestamp for t in stored], [t0, t1])

    def test_equal_timestamp_tick_accepted(self) -> None:
        """Test that a tick with a timestamp equal to the latest stored tick is accepted (non-decreasing)."""
        buf = TickBuffer(max_ticks_per_symbol=5)
        ts = datetime(2024, 1, 1, 0, tzinfo=timezone.utc)
        buf.add_tick(make_tick(symbol="BTC/USD", timestamp=ts))
        buf.add_tick(make_tick(symbol="BTC/USD", timestamp=ts))
        self.assertEqual(len(buf.get_ticks("BTC/USD")), 2)
