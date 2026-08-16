# mypy: disable-error-code="import-untyped"
"""Integration test for the `replay` CLI's --capture-file: replaying twice must be deterministic.

Flow under test: JSONL tick file -> TickReplayReader -> (NATS publish + in-memory strategy
pipeline) -> PipelineCapture -> JSON file. Runs against a real NATS server (required by
replay.py's publisher regardless of --capture-file); no database involved since the capture
pipeline uses PaperTrader's in-memory-only sync path.
"""

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

from Nightwatch.adapters.tick_recorder import MarketTickRecorder
from Nightwatch.cli.replay import main
from tests.fixtures.nats_server import NatsServerFixture
from tests.fixtures.tick_factory import make_tick

_CAPTURE_ENV = {
    "ORDER_NOTIONAL": "100",
    "FEE_RATE": "0.001",
    "INITIAL_CASH": "10000",
    "STRATEGY_WINDOW_SEC": "10.0",
    "STRATEGY_THRESHOLD_PCT": "0.30",
}


@unittest.skipUnless(os.environ.get("RUN_INTEGRATION"), "Integration tests require RUN_INTEGRATION=1")
class TestReplayCaptureIntegration(unittest.TestCase):
    """Running `replay --capture-file` twice against a real NATS server yields identical JSON."""

    nats: NatsServerFixture

    @classmethod
    def setUpClass(cls) -> None:
        cls.nats = NatsServerFixture()
        cls.nats.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.nats.stop()

    def setUp(self) -> None:
        self._prev_nats_servers = os.environ.get("NATS_SERVERS")
        os.environ["NATS_SERVERS"] = self.nats.url
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp_dir.name, "test_ticks.jsonl")

    def tearDown(self) -> None:
        if self._prev_nats_servers is None:
            os.environ.pop("NATS_SERVERS", None)
        else:
            os.environ["NATS_SERVERS"] = self._prev_nats_servers
        self.temp_dir.cleanup()

    def test_replay_twice_produces_identical_capture(self) -> None:
        """Two independent `main()` invocations over the same tick file produce byte-identical JSON."""
        start = datetime.now(timezone.utc)
        recorder = MarketTickRecorder(path=self.path)
        recorder.record_ticks(
            [
                make_tick(price=Decimal("50000"), timestamp=start),
                make_tick(price=Decimal("56000"), timestamp=start + timedelta(seconds=1)),
            ],
        )
        first_path = os.path.join(self.temp_dir.name, "capture_1.json")
        second_path = os.path.join(self.temp_dir.name, "capture_2.json")

        with patch.dict(os.environ, _CAPTURE_ENV):
            main(["--file", self.path, "--speed", "fast", "--capture-file", first_path])
            main(["--file", self.path, "--speed", "fast", "--capture-file", second_path])

        with open(first_path, encoding="utf-8") as fh:
            first_run = fh.read()
        with open(second_path, encoding="utf-8") as fh:
            second_run = fh.read()

        self.assertEqual(first_run, second_run)
        self.assertIn('"type": "signal"', first_run)
        self.assertIn('"type": "fill"', first_run)

    def test_sell_signal_without_position_is_captured_without_order_or_fill(self) -> None:
        """A SELL signal with no held position yields a captured `signal` event but no `order`/`fill`.

        ``create_order_from_signal`` returns ``None`` for a SELL with no position (see
        ``models/order_factory.py``), so the pipeline never reaches ``PaperTrader.process_signal``'s
        order/fill capture calls. This is the "no-op" branch the happy-path golden fixture doesn't cover.
        """
        start = datetime.now(timezone.utc)
        recorder = MarketTickRecorder(path=self.path)
        recorder.record_ticks(
            [
                make_tick(price=Decimal("50000"), timestamp=start),
                make_tick(price=Decimal("30000"), timestamp=start + timedelta(seconds=1)),
            ],
        )
        capture_path = os.path.join(self.temp_dir.name, "capture.json")

        with patch.dict(os.environ, _CAPTURE_ENV):
            main(["--file", self.path, "--speed", "fast", "--capture-file", capture_path])

        with open(capture_path, encoding="utf-8") as fh:
            events = json.load(fh)

        types = [event["type"] for event in events]
        self.assertEqual(types, ["signal"])
        self.assertEqual(events[0]["side"], "SELL")


if __name__ == "__main__":
    unittest.main()
