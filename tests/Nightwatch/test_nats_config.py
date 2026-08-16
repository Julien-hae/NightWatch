"""Unit tests for NatsConnectionConfig defaults."""

import unittest

from Nightwatch.models.nats_config import NatsConnectionConfig


class TestNatsConnectionConfigDefaults(unittest.TestCase):
    """The reconnect interval must stay wide enough to keep outage log volume sane."""

    def test_reconnect_time_wait_defaults_to_two_seconds(self) -> None:
        """A too-aggressive default (nats-py's own) produces an ERROR-level log line every
        ~0.2s per connection during a real outage — confirmed live at ~15 log lines/second
        across the app's three NATS connections. 2s keeps reconnection responsive while
        cutting that volume roughly tenfold.
        """
        config = NatsConnectionConfig(servers=["nats://127.0.0.1:4222"])

        self.assertEqual(config.reconnect_time_wait, 2.0)

    def test_reconnect_attempts_stay_unbounded(self) -> None:
        """The app must always eventually reconnect, never give up — only the interval changed."""
        config = NatsConnectionConfig(servers=["nats://127.0.0.1:4222"])

        self.assertEqual(config.max_reconnect_attempts, -1)


if __name__ == "__main__":
    unittest.main()
