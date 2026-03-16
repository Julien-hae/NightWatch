"""Unit tests for the Signal model in the Nightwatch application."""

import unittest
import uuid
from datetime import datetime, timezone

from Nightwatch.models.signal import Signal
from tests.fixtures.signal_factory import make_signal


class TestSignal(unittest.TestCase):
    """Unit tests for the Signal model."""

    def setUp(self) -> None:
        """Set up any necessary data for the tests."""
        self.signal = make_signal(
            symbol="BTCUSD",
            timestamp=datetime.now(timezone.utc),
            side="BUY",
            strategy="momentum_burst_v1",
            strength=1.0,
            rationale={"delta_pct": 0.05, "window_sec": 3.0, "threshold_pct": 0.02},
            source="trade-service",
            schema_version=1,
        )

    def test_signal_fields(self) -> None:
        """Test that a Signal can be created with the correct attributes."""
        self.assertIsNotNone(self.signal.uid)
        self.assertEqual(self.signal.symbol, "BTCUSD")
        self.assertIsInstance(self.signal.timestamp, datetime)
        self.assertEqual(self.signal.side, "BUY")
        self.assertEqual(self.signal.strength, 1.0)
        self.assertEqual(self.signal.rationale["delta_pct"], 0.05)
        self.assertEqual(self.signal.rationale["window_sec"], 3.0)
        self.assertEqual(self.signal.rationale["threshold_pct"], 0.02)
        self.assertEqual(self.signal.source, "trade-service")
        self.assertEqual(self.signal.schema_version, 1)
        self.assertIsInstance(self.signal.timestamp, datetime)
        self.assertIsInstance(self.signal.uid, uuid.UUID)

    def test_side_only_accepts_buy_or_sell(self) -> None:
        """Test that the 'side' attribute only accepts 'BUY' or 'SELL'."""
        with self.assertRaises(ValueError):
            make_signal(side="ERROR")

    def test_strength_positive_or_null(self) -> None:
        """Test that the 'strength' attribute must be positive or zero."""
        with self.assertRaises(ValueError):
            make_signal(strength=-1.0)

    def test_json_serialization(self) -> None:
        """Test that a Signal can be serialized to JSON and deserialized back correctly."""

        json_data = self.signal.model_dump_json()
        deserialized_signal = Signal.model_validate_json(json_data)
        self.assertEqual(deserialized_signal.uid, self.signal.uid)
        self.assertEqual(deserialized_signal.symbol, self.signal.symbol)
        self.assertEqual(deserialized_signal.timestamp, self.signal.timestamp)
        self.assertEqual(deserialized_signal.side, self.signal.side)
        self.assertEqual(deserialized_signal.strategy, self.signal.strategy)
        self.assertEqual(deserialized_signal.strength, self.signal.strength)
        self.assertEqual(deserialized_signal.rationale, self.signal.rationale)
        self.assertEqual(deserialized_signal.source, self.signal.source)
        self.assertEqual(deserialized_signal.schema_version, self.signal.schema_version)

    def test_json_integration(self) -> None:
        """Test that a Signal can be created from a JSON-like dictionary."""
        json_data = {
            "symbol": "BTCUSD",
            "timestamp": datetime.now(timezone.utc),
            "side": "BUY",
            "strategy": "momentum_burst_v1",
            "strength": 1.0,
            "rationale": {"delta_pct": 0.05, "window_sec": 3.0, "threshold_pct": 0.02},
            "source": "trade-service",
            "schema_version": 1,
        }
        signal_from_json = Signal.model_validate(json_data)
        self.assertEqual(signal_from_json.symbol, "BTCUSD")

    def test_uid_uniqueness(self) -> None:
        """Test that each Signal instance has a unique UUID."""
        signal2 = make_signal()
        self.assertNotEqual(self.signal.uid, signal2.uid)

    def test_empty_or_blank_symbol_raises(self) -> None:
        """Test that an empty or blank symbol raises a validation error."""
        with self.assertRaises(ValueError):
            make_signal(symbol="")
        with self.assertRaises(ValueError):
            make_signal(symbol="   ")

    def test_missing_fields(self) -> None:
        """Test that missing required fields raise a validation error."""
        with self.assertRaises(ValueError):
            Signal(  # type: ignore[call-arg]
                timestamp=datetime.now(timezone.utc),
                side="BUY",
                strategy="momentum_burst_v1",
                strength=1.0,
                rationale={"delta_pct": 0.05, "window_sec": 3.0, "threshold_pct": 0.02},
                source="trade-service",
                schema_version=1,
            )
