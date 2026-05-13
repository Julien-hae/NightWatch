"""Unit tests for the Order model in the Nightwatch application."""

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from Nightwatch.models.order import Order, Status
from Nightwatch.models.signal import Side
from tests.fixtures.order_factory import make_order


class TestOrder(unittest.TestCase):
    """Unit tests for the Order model."""

    def setUp(self) -> None:
        """Set up any necessary data for the tests."""
        self.order = make_order(
            symbol="BTCUSD",
            side=Side.BUY,
            qty=Decimal("1.0"),
            status=Status.NEW,
        )

    def test_order_fields(self) -> None:
        """Test that an Order can be created with the correct attributes."""
        self.assertIsNotNone(self.order.order_id)
        self.assertIsNotNone(self.order.signal_id)
        self.assertIsNotNone(self.order.created_at)
        self.assertEqual(self.order.symbol, "BTCUSD")
        self.assertEqual(self.order.side.value, "BUY")
        self.assertEqual(self.order.qty, Decimal("1.0"))
        self.assertEqual(self.order.status, Status.NEW)

    def test_status_only_accepts_valid_values(self) -> None:
        """Test that the 'status' attribute only accepts valid Status values."""
        with self.assertRaises(AttributeError):
            make_order(status=Status.ERROR)  # type: ignore[attr-defined]

    def test_qty_non_negative(self) -> None:
        """Test that the 'qty' attribute must be strictly positive (> 0)."""
        with self.assertRaises(ValueError):
            make_order(qty=Decimal("0.0"))
        with self.assertRaises(ValueError):
            make_order(qty=Decimal("-1.0"))

    def test_uid_uniqueness(self) -> None:
        """Test that each Order instance has a unique UUID."""
        order2 = make_order()
        self.assertNotEqual(self.order.order_id, order2.order_id)

    def test_empty_or_blank_symbol_raises(self) -> None:
        """Test that an empty or blank symbol raises a validation error."""
        with self.assertRaises(ValueError):
            make_order(symbol="")
        with self.assertRaises(ValueError):
            make_order(symbol="   ")

    def test_missing_fields(self) -> None:
        """Test that missing required fields raise a validation error."""
        with self.assertRaises(ValueError):
            Order(  # type: ignore[call-arg]
                created_at=datetime.now(timezone.utc),
                side=Side.BUY,
            )

    def test_naive_created_at_raises(self) -> None:
        """Test that timezone-naive created_at timestamps are rejected."""
        with self.assertRaises(ValueError):
            make_order(created_at=datetime(2026, 1, 1, 12, 0, 0))

    def test_created_at_is_normalized_to_utc(self) -> None:
        """Test that timezone-aware created_at timestamps are normalized to UTC."""
        local_tz = timezone(timedelta(hours=2))
        order = make_order(created_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=local_tz))
        self.assertEqual(order.created_at.tzinfo, timezone.utc)
        self.assertEqual(order.created_at, datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc))
