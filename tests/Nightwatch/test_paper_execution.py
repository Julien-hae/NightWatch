"""Unit tests for the paper trading execution helper."""

import unittest
from decimal import Decimal

from Nightwatch.models.order import Status
from Nightwatch.models.paper_execution import PercentageFeeModel, paper_execute
from Nightwatch.models.signal import Side
from tests.fixtures.order_factory import make_order


class TestPercentageFeeModel(unittest.TestCase):
    def test_calculate_returns_qty_times_price_times_rate(self) -> None:
        fee_model = PercentageFeeModel(rate=Decimal("0.001"))
        fee = fee_model.calculate(Decimal("0.002"), Decimal("50000"))
        self.assertEqual(fee, Decimal("0.100"))

    def test_zero_rate_yields_zero_fee(self) -> None:
        fee_model = PercentageFeeModel(rate=Decimal("0"))
        self.assertEqual(fee_model.calculate(Decimal("1"), Decimal("123.45")), Decimal("0"))

    def test_negative_rate_rejected(self) -> None:
        with self.assertRaises(Exception):
            PercentageFeeModel(rate=Decimal("-0.001"))


class TestPaperExecute(unittest.TestCase):
    def setUp(self) -> None:
        self.fee_model = PercentageFeeModel(rate=Decimal("0.001"))
        self.order = make_order(
            symbol="BTC/USD",
            side=Side.BUY,
            qty=Decimal("0.002"),
            status=Status.NEW,
        )

    def test_fill_price_equals_last_price(self) -> None:
        fill = paper_execute(self.order, Decimal("50000"), self.fee_model)
        self.assertEqual(fill.price, Decimal("50000"))

    def test_fee_computed_from_notional(self) -> None:
        fill = paper_execute(self.order, Decimal("50000"), self.fee_model)
        self.assertEqual(fill.fee, Decimal("0.100"))

    def test_fill_preserves_order_attributes(self) -> None:
        fill = paper_execute(self.order, Decimal("50000"), self.fee_model)
        self.assertEqual(fill.order_id, self.order.order_id)
        self.assertEqual(fill.symbol, self.order.symbol)
        self.assertEqual(fill.side, self.order.side)
        self.assertEqual(fill.qty, self.order.qty)

    def test_fill_timestamp_is_utc(self) -> None:
        fill = paper_execute(self.order, Decimal("50000"), self.fee_model)
        self.assertIsNotNone(fill.ts.tzinfo)
        self.assertEqual(fill.ts.utcoffset().total_seconds(), 0)  # type: ignore[union-attr]

    def test_zero_price_rejected(self) -> None:
        with self.assertRaises(ValueError):
            paper_execute(self.order, Decimal("0"), self.fee_model)

    def test_negative_price_rejected(self) -> None:
        with self.assertRaises(ValueError):
            paper_execute(self.order, Decimal("-1"), self.fee_model)

    def test_sell_order_executes_at_last_price(self) -> None:
        sell_order = make_order(side=Side.SELL, qty=Decimal("0.5"))
        fill = paper_execute(sell_order, Decimal("60000"), self.fee_model)
        self.assertEqual(fill.side, Side.SELL)
        self.assertEqual(fill.price, Decimal("60000"))
        self.assertEqual(fill.fee, Decimal("30"))

    def test_order_status_transitions_to_filled(self) -> None:
        self.assertEqual(self.order.status, Status.NEW)
        paper_execute(self.order, Decimal("50000"), self.fee_model)
        self.assertEqual(self.order.status, Status.FILLED)

    def test_order_status_unchanged_on_rejected_price(self) -> None:
        with self.assertRaises(ValueError):
            paper_execute(self.order, Decimal("0"), self.fee_model)
        self.assertEqual(self.order.status, Status.NEW)


if __name__ == "__main__":
    unittest.main()
