# mypy: disable-error-code="import-untyped"
"""Golden file regression test for MomentumBurstStrategy: replaying a fixed tick dataset must
reproduce a pinned capture output byte-for-byte.

Flow under test: tests/golden/momentum_v1_ticks.jsonl -> `replay` CLI --capture-file -> compare
against tests/golden/momentum_v1.json. Uses the real `replay` CLI (so it goes through a real NATS
server, same as test_integration_replay_capture.py) rather than calling the pipeline helpers
directly, so this exercises the same code path an operator invokes from the command line. No
database involved: the capture pipeline is PaperTrader's in-memory-only sync path.

If MomentumBurstStrategy's behaviour changes (signal count, side, sizing, ...), the diff between
a fresh capture and the golden file below will show exactly what changed. Regenerate the golden
file deliberately (never to silence a real regression) with:

    poetry run replay --file tests/golden/momentum_v1_ticks.jsonl --speed fast \
        --capture-file tests/golden/momentum_v1.json
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from Nightwatch.cli.replay import main
from tests.fixtures.nats_server import NatsServerFixture

_GOLDEN_TICKS = os.path.join(os.path.dirname(__file__), "..", "golden", "momentum_v1_ticks.jsonl")
_GOLDEN_CAPTURE = os.path.join(os.path.dirname(__file__), "..", "golden", "momentum_v1.json")

_STRATEGY_ENV = {
    "ORDER_NOTIONAL": "100",
    "FEE_RATE": "0.001",
    "INITIAL_CASH": "10000",
    "STRATEGY_WINDOW_SEC": "10.0",
    "STRATEGY_THRESHOLD_PCT": "0.30",
}


@unittest.skipUnless(os.environ.get("RUN_INTEGRATION"), "Integration tests require RUN_INTEGRATION=1")
class TestGoldenMomentumCapture(unittest.TestCase):
    """Replaying the pinned momentum_v1 tick dataset must match its pinned golden capture file."""

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

    def tearDown(self) -> None:
        if self._prev_nats_servers is None:
            os.environ.pop("NATS_SERVERS", None)
        else:
            os.environ["NATS_SERVERS"] = self._prev_nats_servers
        self.temp_dir.cleanup()

    def _replay(self, capture_path: str, env_overrides: dict[str, str] | None = None) -> None:
        """Invoke the `replay` CLI against the golden tick dataset, writing a capture to *capture_path*."""
        env = {**_STRATEGY_ENV, **(env_overrides or {})}
        with patch.dict(os.environ, env):
            main(["--file", _GOLDEN_TICKS, "--speed", "fast", "--capture-file", capture_path])

    def test_replay_matches_golden_capture(self) -> None:
        """Replaying the golden dataset with production-shaped config reproduces the golden capture file."""
        with open(_GOLDEN_CAPTURE, encoding="utf-8") as fh:
            expected = json.load(fh)

        actual_path = os.path.join(self.temp_dir.name, "actual_capture.json")
        self._replay(actual_path)

        with open(actual_path, encoding="utf-8") as fh:
            actual = json.load(fh)

        self.assertEqual(actual, expected)

    def test_modified_threshold_diverges_from_golden(self) -> None:
        """A changed STRATEGY_THRESHOLD_PCT alters strategy behaviour, so the capture no longer matches golden."""
        with open(_GOLDEN_CAPTURE, encoding="utf-8") as fh:
            expected = json.load(fh)

        actual_path = os.path.join(self.temp_dir.name, "actual_capture.json")
        self._replay(actual_path, env_overrides={"STRATEGY_THRESHOLD_PCT": "15.0"})

        with open(actual_path, encoding="utf-8") as fh:
            actual = json.load(fh)

        self.assertNotEqual(actual, expected)
        self.assertEqual([event for event in actual if event["type"] == "signal"], [])


if __name__ == "__main__":
    unittest.main()
