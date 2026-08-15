# mypy: disable-error-code="import-untyped"
"""Integration tests for the `replay` CLI: file -> NATS -> subscriber.

Flow under test: JSONL tick file -> TickReplayReader -> MarketTickPublisher -> subscriber receives.

`main()` manages its own event loop internally (via ``asyncio.run``), so each test drives its
NATS subscriber on a separate loop and calls `main()` synchronously in between -- nesting
`main()`'s `asyncio.run()` inside another running loop would raise ``RuntimeError``.
"""

import asyncio
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone

from nats.aio.client import Client as NatsClient

from Nightwatch.adapters.tick_recorder import MarketTickRecorder
from Nightwatch.cli.replay import main
from tests.fixtures.nats_server import NatsServerFixture
from tests.fixtures.tick_factory import make_tick


@unittest.skipUnless(os.environ.get("RUN_INTEGRATION"), "Integration tests require RUN_INTEGRATION=1")
class TestReplayPublisherIntegration(unittest.TestCase):
    """Integration tests for the replay CLI publishing ticks over a real NATS connection."""

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
        self.loop = asyncio.new_event_loop()

    def tearDown(self) -> None:
        self.loop.close()
        if self._prev_nats_servers is None:
            os.environ.pop("NATS_SERVERS", None)
        else:
            os.environ["NATS_SERVERS"] = self._prev_nats_servers
        self.temp_dir.cleanup()

    def test_fast_replay_subscriber_receives_all_ticks_in_order(self) -> None:
        """`--speed fast` publishes every tick; a subscriber receives them all, in order."""
        ticks = [make_tick(), make_tick(symbol="ETH/USD"), make_tick(symbol="LTC/USD")]
        recorder = MarketTickRecorder(path=self.path)
        recorder.record_ticks(ticks)

        sub_client = NatsClient()
        self.loop.run_until_complete(sub_client.connect(servers=[self.nats.url]))
        sub = self.loop.run_until_complete(sub_client.subscribe("market.tick.BTCUSD"))
        sub_eth = self.loop.run_until_complete(sub_client.subscribe("market.tick.ETHUSD"))
        sub_ltc = self.loop.run_until_complete(sub_client.subscribe("market.tick.LTCUSD"))
        self.loop.run_until_complete(sub_client.flush())

        main(["--file", self.path, "--speed", "fast"])

        msg = self.loop.run_until_complete(asyncio.wait_for(sub.next_msg(), timeout=5))
        msg_eth = self.loop.run_until_complete(asyncio.wait_for(sub_eth.next_msg(), timeout=5))
        msg_ltc = self.loop.run_until_complete(asyncio.wait_for(sub_ltc.next_msg(), timeout=5))

        self.assertIn(str(ticks[0].uid), msg.data.decode())
        self.assertIn(str(ticks[1].uid), msg_eth.data.decode())
        self.assertIn(str(ticks[2].uid), msg_ltc.data.decode())

        self.loop.run_until_complete(sub_client.drain())

    def test_real_replay_reproduces_timestamp_gap(self) -> None:
        """`--speed real` sleeps between ticks, taking roughly as long as the recorded gap."""
        start = datetime.now(timezone.utc)
        ticks = [
            make_tick(timestamp=start),
            make_tick(symbol="ETH/USD", timestamp=start + timedelta(seconds=0.5)),
        ]
        recorder = MarketTickRecorder(path=self.path)
        recorder.record_ticks(ticks)

        sub_client = NatsClient()
        self.loop.run_until_complete(sub_client.connect(servers=[self.nats.url]))
        sub = self.loop.run_until_complete(sub_client.subscribe("market.tick.BTCUSD"))
        sub_eth = self.loop.run_until_complete(sub_client.subscribe("market.tick.ETHUSD"))
        self.loop.run_until_complete(sub_client.flush())

        elapsed_start = time.monotonic()
        main(["--file", self.path, "--speed", "real"])
        elapsed = time.monotonic() - elapsed_start

        self.loop.run_until_complete(asyncio.wait_for(sub.next_msg(), timeout=5))
        self.loop.run_until_complete(asyncio.wait_for(sub_eth.next_msg(), timeout=5))

        self.assertGreaterEqual(elapsed, 0.5)

        self.loop.run_until_complete(sub_client.drain())


if __name__ == "__main__":
    unittest.main()
