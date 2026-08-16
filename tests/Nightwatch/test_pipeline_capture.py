# mypy: disable-error-code="import-untyped"
"""Unit tests for PipelineCapture: deterministic JSON capture of signals/orders/fills."""

import json
import os
import tempfile
import unittest
from decimal import Decimal

from Nightwatch.pipeline.capture import PipelineCapture
from tests.fixtures.fill_factory import make_fill
from tests.fixtures.order_factory import make_order
from tests.fixtures.signal_factory import make_signal


class TestPipelineCapture(unittest.TestCase):
    """Test that PipelineCapture records only deterministic business fields as JSON events."""

    def test_on_signal_records_business_fields_without_uid(self) -> None:
        """A captured signal event has no uid/timestamp field, only business fields."""
        capture = PipelineCapture()
        signal = make_signal(rationale={"delta_pct": 0.35})

        capture.on_signal(signal)

        event = capture.events()[0]
        self.assertEqual(
            event,
            {
                "type": "signal",
                "symbol": signal.symbol,
                "side": "BUY",
                "strategy": signal.strategy,
                "strength": signal.strength,
                "delta_pct": 0.35,
            },
        )

    def test_on_order_records_business_fields_without_ids(self) -> None:
        """A captured order event has no order_id/signal_id/created_at field."""
        capture = PipelineCapture()
        order = make_order(qty=Decimal("0.5"))

        capture.on_order(order)

        event = capture.events()[0]
        self.assertEqual(
            event,
            {
                "type": "order",
                "symbol": order.symbol,
                "side": "BUY",
                "qty": "0.5",
                "status": "NEW",
            },
        )

    def test_on_fill_records_business_fields_without_ids(self) -> None:
        """A captured fill event has no fill_id/order_id/ts field."""
        capture = PipelineCapture()
        fill = make_fill(qty=Decimal("0.002"), price=Decimal("50000"), fee=Decimal("0.05"))

        capture.on_fill(fill)

        event = capture.events()[0]
        self.assertEqual(
            event,
            {
                "type": "fill",
                "symbol": fill.symbol,
                "side": "BUY",
                "qty": "0.002",
                "price": "50000",
                "fee": "0.05",
            },
        )

    def test_events_preserve_emission_order(self) -> None:
        """Captured events appear in the JSON array in the order they were recorded."""
        capture = PipelineCapture()
        capture.on_signal(make_signal())
        capture.on_order(make_order())
        capture.on_fill(make_fill())

        types = [event["type"] for event in capture.events()]
        self.assertEqual(types, ["signal", "order", "fill"])

    def test_write_produces_valid_json_array(self) -> None:
        """write() dumps all captured events as a JSON array readable back with json.load."""
        capture = PipelineCapture()
        capture.on_signal(make_signal())

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "capture.json")
            capture.write(path)

            with open(path, encoding="utf-8") as fh:
                loaded = json.load(fh)

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["type"], "signal")

    def test_write_serializes_decimal_rationale_values(self) -> None:
        """A Decimal value in signal.rationale (e.g. delta_pct) does not break JSON serialization."""
        capture = PipelineCapture()
        capture.on_signal(make_signal(rationale={"delta_pct": Decimal("0.35")}))

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "capture.json")
            capture.write(path)

            with open(path, encoding="utf-8") as fh:
                loaded = json.load(fh)

        self.assertEqual(loaded[0]["delta_pct"], "0.35")


if __name__ == "__main__":
    unittest.main()
