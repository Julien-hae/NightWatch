"""Integration tests for the MarketTickRecorder class, which records MarketTick data to a file."""

import json
import os
import unittest
from datetime import datetime, timezone

from Nightwatch.models.market_tick import MarketTick
from Nightwatch.tick_recorder import MarketTickRecorder


class TestMarketTickRecorder(unittest.TestCase):
    """Test that each ticks are recorded into a file in the correct format and in the correct order."""

    def setUp(self) -> None:
        self.tick_recorder = MarketTickRecorder(path="test_data/test_ticks.jsonl")
        self.tick1 = MarketTick(timestamp=datetime.now(timezone.utc), symbol="BTC/USD", price=42000.0, source="Kraken", schema_version=1)
        self.tick2 = MarketTick(timestamp=datetime.now(timezone.utc), symbol="ETH/USD", price=3000.0, source="Kraken", schema_version=1)
        self.tick3 = MarketTick(timestamp=datetime.now(timezone.utc), symbol="LTC/USD", price=150.0, source="Kraken", schema_version=1)

    def test_record_ticks(self) -> None:
        """Test that ticks are recorded in the correct format and order."""
        if os.path.exists(self.tick_recorder.path):
            os.remove(self.tick_recorder.path)
        self.tick_recorder.record_tick(self.tick1)
        self.tick_recorder.record_tick(self.tick2)
        self.tick_recorder.record_tick(self.tick3)

        with open(self.tick_recorder.path, "r") as f:
            lines = f.readlines()
            self.assertEqual(len(lines), 3)
            self.assertEqual(lines[0].strip(), self.tick1.model_dump_json())
            self.assertEqual(lines[1].strip(), self.tick2.model_dump_json())
            self.assertEqual(lines[2].strip(), self.tick3.model_dump_json())

    def test_valid_jsonl_format(self) -> None:
        """Test that the recorded ticks are in valid JSONL format."""
        self.tick_recorder.record_tick(self.tick1)
        self.tick_recorder.record_tick(self.tick2)

        with open(self.tick_recorder.path, "r") as f:
            lines = f.readlines()
            for line in lines:
                try:
                    json.loads(line)
                    print(f"Line is valid JSON: {line.strip()}")
                except json.JSONDecodeError:
                    self.fail(f"Line is not valid JSON: {line.strip()}")

    def test_file_creation(self) -> None:
        """Test that the file is created if it does not exist."""
        if os.path.exists(self.tick_recorder.path):
            os.remove(self.tick_recorder.path)

        self.tick_recorder.record_tick(self.tick1)
        self.assertTrue(os.path.exists(self.tick_recorder.path))
