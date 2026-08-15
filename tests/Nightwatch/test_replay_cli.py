# mypy: disable-error-code="import-untyped"
"""Unit tests for the `replay` CLI entrypoint."""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from Nightwatch.adapters.tick_recorder import MarketTickRecorder
from Nightwatch.cli.replay import main
from Nightwatch.metrics.metrics import NightwatchMetrics
from tests.fixtures.tick_factory import make_tick


class TestReplayCli(unittest.TestCase):
    """Test that the replay CLI reads a tick file and republishes every tick to NATS."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp_dir.name, "test_ticks.jsonl")
        patcher = patch("Nightwatch.cli.replay.MarketTickPublisher")
        self.mock_publisher_cls = patcher.start()
        self.addCleanup(patcher.stop)
        self.mock_publisher = self.mock_publisher_cls.return_value
        self.mock_publisher.connect = AsyncMock()
        self.mock_publisher.publish = AsyncMock()
        self.mock_publisher.close = AsyncMock()
        self.mock_publisher.client.flush = AsyncMock()

    def tearDown(self) -> None:
        """Clean up the test file after tests are done."""
        self.temp_dir.cleanup()

    def test_main_reads_file_without_raising(self) -> None:
        """Given a valid JSONL file, main() runs to completion."""
        recorder = MarketTickRecorder(path=self.path)
        recorder.record_ticks([make_tick(), make_tick(symbol="ETH/USD")])

        main(["--file", self.path])

        self.assertEqual(self.mock_publisher.publish.await_count, 2)

    def test_main_defaults_speed_to_fast(self) -> None:
        """main() accepts a bare --file, defaulting --speed to 'fast'."""
        recorder = MarketTickRecorder(path=self.path)
        recorder.record_tick(make_tick())

        main(["--file", self.path])

        self.mock_publisher.publish.assert_awaited_once()

    def test_main_accepts_real_speed(self) -> None:
        """main() accepts --speed real without raising."""
        recorder = MarketTickRecorder(path=self.path)
        recorder.record_tick(make_tick())

        main(["--file", self.path, "--speed", "real"])

        self.mock_publisher.publish.assert_awaited_once()

    def test_main_requires_file_argument(self) -> None:
        """main() exits with an error when --file is missing."""
        with self.assertRaises(SystemExit):
            main([])

    def test_fast_speed_does_not_sleep(self) -> None:
        """--speed fast never sleeps between ticks."""
        recorder = MarketTickRecorder(path=self.path)
        recorder.record_ticks([make_tick(), make_tick(symbol="ETH/USD")])

        with patch("Nightwatch.cli.replay.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            main(["--file", self.path, "--speed", "fast"])

        mock_sleep.assert_not_awaited()

    def test_real_speed_sleeps_between_ticks(self) -> None:
        """--speed real sleeps once between two ticks based on their timestamp delta."""
        start = datetime.now(timezone.utc)
        recorder = MarketTickRecorder(path=self.path)
        recorder.record_ticks(
            [
                make_tick(timestamp=start),
                make_tick(symbol="ETH/USD", timestamp=start + timedelta(seconds=2)),
            ],
        )

        with patch("Nightwatch.cli.replay.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            main(["--file", self.path, "--speed", "real"])

        mock_sleep.assert_awaited_once()
        assert mock_sleep.await_args is not None
        self.assertAlmostEqual(mock_sleep.await_args.args[0], 2.0, places=3)

    def test_publish_failure_on_one_tick_does_not_abort_replay(self) -> None:
        """A publish failure on one tick is logged and the remaining ticks still publish."""
        recorder = MarketTickRecorder(path=self.path)
        recorder.record_ticks([make_tick(), make_tick(symbol="ETH/USD"), make_tick(symbol="LTC/USD")])
        self.mock_publisher.publish.side_effect = [Exception("boom"), None, None]

        main(["--file", self.path])

        self.assertEqual(self.mock_publisher.publish.await_count, 3)
        self.mock_publisher.close.assert_awaited_once()

    def test_replay_ticks_total_incremented_per_symbol(self) -> None:
        """Each successfully published tick increments replay_ticks_total, labelled by symbol."""
        recorder = MarketTickRecorder(path=self.path)
        recorder.record_ticks([make_tick(), make_tick(), make_tick(symbol="ETH/USD")])
        metrics = NightwatchMetrics()

        main(["--file", self.path], metrics=metrics)

        self.assertEqual(metrics.get_counter_value(metrics.replay_ticks_total, symbol="BTC/USD"), 2.0)
        self.assertEqual(metrics.get_counter_value(metrics.replay_ticks_total, symbol="ETH/USD"), 1.0)

    def test_replay_ticks_total_not_incremented_on_publish_failure(self) -> None:
        """A tick that fails to publish does not count toward replay_ticks_total."""
        recorder = MarketTickRecorder(path=self.path)
        recorder.record_ticks([make_tick(), make_tick(symbol="ETH/USD")])
        self.mock_publisher.publish.side_effect = [Exception("boom"), None]
        metrics = NightwatchMetrics()

        main(["--file", self.path], metrics=metrics)

        self.assertIsNone(metrics.get_counter_value(metrics.replay_ticks_total, symbol="BTC/USD"))
        self.assertEqual(metrics.get_counter_value(metrics.replay_ticks_total, symbol="ETH/USD"), 1.0)

    def test_replay_duration_seconds_observed(self) -> None:
        """A single observation is recorded on replay_duration_seconds per run."""
        recorder = MarketTickRecorder(path=self.path)
        recorder.record_tick(make_tick())
        metrics = NightwatchMetrics()

        main(["--file", self.path], metrics=metrics)

        sample_count = next(
            sample.value
            for family in metrics.replay_duration_seconds.collect()
            for sample in family.samples
            if sample.name.endswith("_count")
        )
        self.assertEqual(sample_count, 1.0)

    def test_start_and_end_events_are_logged(self) -> None:
        """main() logs a replay_start event before running and a replay_end event after."""
        recorder = MarketTickRecorder(path=self.path)
        recorder.record_tick(make_tick())

        with self.assertLogs("Nightwatch.cli.replay", level="INFO") as cm:
            main(["--file", self.path])

        events = [json.loads(line.split(":", 2)[-1]) for line in cm.output if '"event"' in line]
        self.assertEqual(events[0]["event"], "replay_start")
        self.assertEqual(events[0]["file"], self.path)
        self.assertEqual(events[-1]["event"], "replay_end")
        self.assertEqual(events[-1]["tick_count"], 1)


if __name__ == "__main__":
    unittest.main()
