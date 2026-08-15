# mypy: disable-error-code="import-untyped"
"""Unit tests for the TickReplayReader class, which reads MarketTick data from JSONL files."""

import os
import tempfile
import unittest
from decimal import Decimal

from Nightwatch.adapters.tick_recorder import MarketTickRecorder
from Nightwatch.adapters.tick_replay_reader import TickReplayReader
from Nightwatch.metrics.metrics import NightwatchMetrics
from tests.fixtures.tick_factory import make_tick


class TestTickReplayReader(unittest.TestCase):
    """Test that ticks are read back from a JSONL file in the correct order, tolerating bad lines."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp_dir.name, "test_ticks.jsonl")
        self.tick1 = make_tick()
        self.tick2 = make_tick(symbol="ETH/USD", price=Decimal("3000.0"))
        self.tick3 = make_tick(symbol="LTC/USD", price=Decimal("150.0"))

    def tearDown(self) -> None:
        """Clean up the test file after tests are done."""
        self.temp_dir.cleanup()

    def test_read_ticks_returns_same_count_and_order(self) -> None:
        """N recorded lines produce N ticks, in their original order."""
        recorder = MarketTickRecorder(path=self.path)
        recorder.record_ticks([self.tick1, self.tick2, self.tick3])

        reader = TickReplayReader(path=self.path)
        ticks = reader.read_ticks()

        self.assertEqual(len(ticks), 3)
        self.assertEqual([t.uid for t in ticks], [self.tick1.uid, self.tick2.uid, self.tick3.uid])

    def test_iter_ticks_is_a_generator_in_order(self) -> None:
        """iter_ticks() yields ticks lazily, in the same order as read_ticks()."""
        recorder = MarketTickRecorder(path=self.path)
        recorder.record_ticks([self.tick1, self.tick2])

        reader = TickReplayReader(path=self.path)
        ticks = list(reader.iter_ticks())

        self.assertEqual([t.uid for t in ticks], [self.tick1.uid, self.tick2.uid])

    def test_invalid_json_line_is_skipped_without_raising(self) -> None:
        """A malformed JSON line is logged and skipped; surrounding valid ticks still come back."""
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(self.tick1.model_dump_json() + "\n")
            f.write("{not valid json\n")
            f.write(self.tick2.model_dump_json() + "\n")

        reader = TickReplayReader(path=self.path)
        ticks = reader.read_ticks()

        self.assertEqual([t.uid for t in ticks], [self.tick1.uid, self.tick2.uid])

    def test_schema_invalid_line_is_skipped_without_raising(self) -> None:
        """A line that is valid JSON but fails MarketTick validation is logged and skipped."""
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(self.tick1.model_dump_json() + "\n")
            f.write('{"symbol": "BTC/USD"}\n')  # missing required fields
            f.write(self.tick2.model_dump_json() + "\n")

        reader = TickReplayReader(path=self.path)
        ticks = reader.read_ticks()

        self.assertEqual([t.uid for t in ticks], [self.tick1.uid, self.tick2.uid])

    def test_blank_lines_are_skipped(self) -> None:
        """Blank lines between valid ticks are ignored."""
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(self.tick1.model_dump_json() + "\n")
            f.write("\n")
            f.write("   \n")
            f.write(self.tick2.model_dump_json() + "\n")

        reader = TickReplayReader(path=self.path)
        ticks = reader.read_ticks()

        self.assertEqual([t.uid for t in ticks], [self.tick1.uid, self.tick2.uid])

    def test_empty_file_returns_empty_list(self) -> None:
        """An empty file produces no ticks."""
        open(self.path, "w", encoding="utf-8").close()

        reader = TickReplayReader(path=self.path)
        ticks = reader.read_ticks()

        self.assertEqual(ticks, [])

    def test_invalid_line_increments_parse_errors_metric(self) -> None:
        """Each unparsable line increments the shared parse_errors_total counter."""
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{not valid json\n")
            f.write('{"symbol": "BTC/USD"}\n')
            f.write(self.tick1.model_dump_json() + "\n")

        metrics = NightwatchMetrics()
        reader = TickReplayReader(path=self.path, metrics=metrics)
        ticks = reader.read_ticks()

        self.assertEqual(len(ticks), 1)
        metric_families = list(metrics.parse_errors_total.collect())
        value = metric_families[0].samples[0].value
        self.assertEqual(value, 2.0)


if __name__ == "__main__":
    unittest.main()
