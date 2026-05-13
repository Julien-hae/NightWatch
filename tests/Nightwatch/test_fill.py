"""Unit tests for the Fill model in the Nightwatch application."""

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from Nightwatch.models.fill import Fill
from Nightwatch.models.signal import Side
from tests.fixtures.fill_factory import make_fill


class TestFill(unittest.TestCase):
    """Unit tests for the Fill model."""

    def setUp(self) -> None:
        """Set up any necessary data for the tests."""
        self.fill = make_fill(
            symbol="BTCUSD",
            side=Side.BUY,
            qty=Decimal("1.0"),
            price=Decimal("50000.0"),
            fee=Decimal("0.0"),
        )

    def test_fill_fields(self) -> None:
        """Test that a Fill can be created with the correct attributes."""
        self.assertIsNotNone(self.fill.fill_id)
        self.assertIsNotNone(self.fill.order_id)
        self.assertIsNotNone(self.fill.ts)
        self.assertEqual(self.fill.symbol, "BTCUSD")
        self.assertEqual(self.fill.side.value, "BUY")
        self.assertEqual(self.fill.qty, Decimal("1.0"))
        self.assertEqual(self.fill.price, Decimal("50000.0"))
        self.assertEqual(self.fill.fee, Decimal("0.0"))

    def test_price_strictly_positive(self) -> None:
        """Test that the 'price' attribute must be strictly positive (> 0)."""
        with self.assertRaises(ValueError):
            make_fill(price=Decimal("0.0"))
        with self.assertRaises(ValueError):
            make_fill(price=Decimal("-1.0"))

    def test_qty_strictly_positive(self) -> None:
        """Test that the 'qty' attribute must be strictly positive (> 0)."""
        with self.assertRaises(ValueError):
            make_fill(qty=Decimal("0.0"))
        with self.assertRaises(ValueError):
            make_fill(qty=Decimal("-1.0"))

    def test_fee_non_negative(self) -> None:
        """Test that the 'fee' attribute must be non-negative (>= 0)."""
        with self.assertRaises(ValueError):
            make_fill(fee=Decimal("-1.0"))

    def test_uid_uniqueness(self) -> None:
        """Test that each Fill instance has a unique UUID."""
        fill2 = make_fill()
        self.assertNotEqual(self.fill.fill_id, fill2.fill_id)

    def test_empty_or_blank_symbol_raises(self) -> None:
        """Test that an empty or blank symbol raises a validation error."""
        with self.assertRaises(ValueError):
            make_fill(symbol="")
        with self.assertRaises(ValueError):
            make_fill(symbol="   ")

    def test_missing_fields(self) -> None:
        """Test that missing required fields raise a validation error."""
        with self.assertRaises(ValueError):
            Fill(  # type: ignore[call-arg]
                ts=datetime.now(timezone.utc),
                side=Side.BUY,
            )

    def test_naive_ts_raises(self) -> None:
        """Test that timezone-naive ts timestamps are rejected."""
        with self.assertRaises(ValueError):
            make_fill(ts=datetime(2026, 1, 1, 12, 0, 0))

    def test_ts_is_normalized_to_utc(self) -> None:
        """Test that timezone-aware ts timestamps are normalized to UTC."""
        local_tz = timezone(timedelta(hours=2))
        fill = make_fill(ts=datetime(2026, 1, 1, 12, 0, 0, tzinfo=local_tz))
        self.assertEqual(fill.ts.tzinfo, timezone.utc)
        self.assertEqual(fill.ts, datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc))
