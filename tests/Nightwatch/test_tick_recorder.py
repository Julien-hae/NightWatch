"""Integration tests for the MarketTickRecorder class, which records MarketTick data to a file."""

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal

from Nightwatch.models.market_tick import MarketTick
from Nightwatch.tick_recorder import MarketTickRecorder


@unittest.skipUnless(os.environ.get("RUN_INTEGRATION"), "Integration tests require RUN_INTEGRATION=1")
class TestMarketTickRecorder(unittest.TestCase):
    """Test that each tick are recorded into a file in the correct format and in the correct order."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp_dir.name, "test_ticks.jsonl")
        self.tick_recorder = MarketTickRecorder(path=self.path)
        self.tick1 = MarketTick(
            timestamp=datetime.now(timezone.utc), symbol="BTC/USD", price=Decimal("42000.0"), source="Kraken", schema_version=1
        )
        self.tick2 = MarketTick(
            timestamp=datetime.now(timezone.utc), symbol="ETH/USD", price=Decimal("3000.0"), source="Kraken", schema_version=1
        )
        self.tick3 = MarketTick(
            timestamp=datetime.now(timezone.utc), symbol="LTC/USD", price=Decimal("150.0"), source="Kraken", schema_version=1
        )

    def test_record_ticks(self) -> None:
        """Test that ticks are recorded in the correct format and order."""
        self.tick_recorder.record_tick(self.tick1)
        self.tick_recorder.record_tick(self.tick2)
        self.tick_recorder.record_tick(self.tick3)

        with open(self.tick_recorder.path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            self.assertEqual(len(lines), 3)
            self.assertEqual(lines[0].strip(), self.tick1.model_dump_json())
            self.assertEqual(lines[1].strip(), self.tick2.model_dump_json())
            self.assertEqual(lines[2].strip(), self.tick3.model_dump_json())

    def test_record_multiple_ticks(self) -> None:
        """Test that multiple ticks are recorded in the correct format and order."""
        self.tick_recorder.record_ticks([self.tick1, self.tick2, self.tick3])

        with open(self.tick_recorder.path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            self.assertEqual(len(lines), 3)
            self.assertEqual(lines[0].strip(), self.tick1.model_dump_json())
            self.assertEqual(lines[1].strip(), self.tick2.model_dump_json())
            self.assertEqual(lines[2].strip(), self.tick3.model_dump_json())

    def test_valid_jsonl_format(self) -> None:
        """Test that the recorded ticks are in valid JSONL format."""
        self.tick_recorder.record_tick(self.tick1)
        self.tick_recorder.record_tick(self.tick2)

        with open(self.tick_recorder.path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            for line in lines:
                try:
                    json.loads(line)
                except json.JSONDecodeError:
                    self.fail(f"Line is not valid JSON: {line.strip()}")

    def test_file_creation(self) -> None:
        """Test that the file is created if it does not exist."""
        self.tick_recorder.record_tick(self.tick1)
        self.assertTrue(os.path.exists(self.tick_recorder.path))

    def tearDown(self) -> None:
        """Clean up the test file after tests are done."""
        self.temp_dir.cleanup()
