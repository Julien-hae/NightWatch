"""Unit tests for the BotControlEvent model."""

import unittest
from datetime import datetime, timezone

from Nightwatch.models.bot_control_event import BotControlEvent


class TestBotControlEvent(unittest.TestCase):
    """Unit tests for the BotControlEvent model."""

    def test_valid_bot_control_event(self) -> None:
        """Test that a valid BotControlEvent can be created."""
        event = BotControlEvent(
            kill=True,
            timestamp=datetime.now(timezone.utc),
            reason="Testing bot control event",
        )
        self.assertTrue(event.kill)
        self.assertIsInstance(event.timestamp, datetime)
        self.assertEqual(event.reason, "Testing bot control event")

    def test_reason_cannot_be_blank(self) -> None:
        """Test that the reason field cannot be blank or just whitespace."""
        with self.assertRaises(ValueError):
            BotControlEvent(
                kill=True,
                timestamp=datetime.now(timezone.utc),
                reason="   ",  # Just whitespace
            )

    def test_json_roundtrip(self) -> None:
        """Test that a BotControlEvent can be serialized to JSON and deserialized back."""
        event = BotControlEvent(
            kill=False,
            timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            reason="Scheduled maintenance",
        )
        json_data = event.model_dump_json()
        deserialized_event = BotControlEvent.model_validate_json(json_data)
        self.assertEqual(event.kill, deserialized_event.kill)
        self.assertEqual(event.timestamp, deserialized_event.timestamp)
        self.assertEqual(event.reason, deserialized_event.reason)

    def test_kill_is_boolean(self) -> None:
        """Test that the kill field must be a boolean."""
        with self.assertRaises(ValueError):
            BotControlEvent(
                kill="yes",  # type: ignore[arg-type]
                timestamp=datetime.now(timezone.utc),
                reason="Invalid kill value",
            )
