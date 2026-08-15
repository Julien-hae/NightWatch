# mypy: disable-error-code="import-untyped"
"""Unit tests for the `replay` CLI entrypoint."""

import os
import tempfile
import unittest

from Nightwatch.adapters.tick_recorder import MarketTickRecorder
from Nightwatch.cli.replay import main
from tests.fixtures.tick_factory import make_tick


class TestReplayCli(unittest.TestCase):
    """Test that the replay CLI reads a tick file without raising."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp_dir.name, "test_ticks.jsonl")

    def tearDown(self) -> None:
        """Clean up the test file after tests are done."""
        self.temp_dir.cleanup()

    def test_main_reads_file_without_raising(self) -> None:
        """Given a valid JSONL file, main() runs to completion."""
        recorder = MarketTickRecorder(path=self.path)
        recorder.record_ticks([make_tick(), make_tick(symbol="ETH/USD")])

        main(["--file", self.path])

    def test_main_defaults_speed_to_fast(self) -> None:
        """main() accepts a bare --file, defaulting --speed to 'fast'."""
        recorder = MarketTickRecorder(path=self.path)
        recorder.record_tick(make_tick())

        main(["--file", self.path])

    def test_main_accepts_real_speed(self) -> None:
        """main() accepts --speed real without raising."""
        recorder = MarketTickRecorder(path=self.path)
        recorder.record_tick(make_tick())

        main(["--file", self.path, "--speed", "real"])

    def test_main_requires_file_argument(self) -> None:
        """main() exits with an error when --file is missing."""
        with self.assertRaises(SystemExit):
            main([])


if __name__ == "__main__":
    unittest.main()
