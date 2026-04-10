# mypy: disable-error-code="import-untyped"
"""Integration tests for the MarketTickPublisher with a real NATS server."""

import asyncio
import json
import os
import unittest
from collections.abc import Coroutine
from decimal import Decimal
from typing import Any
from unittest.mock import patch

from nats.aio.client import Client as NatsClient

from Nightwatch.messaging.publisher import MAX_PAYLOAD_BYTES, MarketTickPublisher, PayloadTooLargeError
from Nightwatch.models.market_tick import MarketTick
from Nightwatch.models.nats_config import NatsConnectionConfig
from tests.fixtures.nats_server import NatsServerFixture
from tests.fixtures.tick_factory import make_tick


@unittest.skipUnless(os.environ.get("RUN_INTEGRATION"), "Integration tests require RUN_INTEGRATION=1")
class TestMarketTickPublisherIntegration(unittest.TestCase):
    """Integration tests that start / stop a real NATS server."""

    nats: NatsServerFixture

    @classmethod
    def setUpClass(cls) -> None:
        """Start a NATS server before the test suite runs."""
        cls.nats = NatsServerFixture()
        cls.nats.start()

    @classmethod
    def tearDownClass(cls) -> None:
        """Stop the NATS server after the test suite completes."""
        cls.nats.stop()

    @staticmethod
    def _run(coro: Coroutine[Any, Any, Any]) -> Any:
        """Run a coroutine in a new event loop (avoids loop reuse issues)."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_connect_to_nats(self) -> None:
        """Publisher connects to the NATS server without error."""

        async def _test() -> None:
            pub = MarketTickPublisher(config=NatsConnectionConfig(servers=[self.nats.url]))
            await pub.connect()
            self.assertTrue(pub.client.is_connected)
            await pub.close()

        self._run(_test())

    def test_publish_tick(self) -> None:
        """Publishing a MarketTick succeeds and returns the correct subject."""

        async def _test() -> None:
            pub = MarketTickPublisher(config=NatsConnectionConfig(servers=[self.nats.url]))
            await pub.connect()

            tick = make_tick()
            subject = await pub.publish(tick)

            self.assertEqual(subject, "market.tick.BTCUSD")
            await pub.close()

        self._run(_test())

    def test_subscriber_receives_tick(self) -> None:
        """A NATS subscriber receives the exact MarketTick that was published."""

        async def _test() -> None:
            received: list[bytes] = []

            sub_client = NatsClient()
            await sub_client.connect(servers=[self.nats.url], token=os.getenv("NATS_TOKEN", ""))
            sub = await sub_client.subscribe("market.tick.BTCUSD")

            pub = MarketTickPublisher(config=NatsConnectionConfig(servers=[self.nats.url]))
            await pub.connect()
            tick = make_tick()
            await pub.publish(tick)

            try:
                msg = await sub.next_msg(timeout=2)
                received.append(msg.data)
            except asyncio.TimeoutError:
                self.fail("Timed out waiting for NATS message on subject 'market.tick.BTCUSD' within 2 seconds")

            self.assertEqual(len(received), 1, "Expected exactly one message")
            payload = json.loads(received[0])
            self.assertEqual(payload["symbol"], tick.symbol)
            self.assertEqual(Decimal(payload["price"]), Decimal(tick.price))
            self.assertEqual(payload["source"], tick.source)
            self.assertEqual(payload["schema_version"], tick.schema_version)

            reconstructed = MarketTick(**payload)
            self.assertEqual(reconstructed.symbol, tick.symbol)
            self.assertEqual(Decimal(reconstructed.price), Decimal(tick.price))
            self.assertEqual(reconstructed.uid, tick.uid)

            await pub.close()
            await sub_client.drain()

        self._run(_test())

    def test_reconnect_after_server_restart(self) -> None:
        """After killing and restarting NATS, the publisher reconnects and can publish again."""

        async def _test() -> None:
            disconnected = asyncio.Event()
            reconnected = asyncio.Event()

            async def _on_disconnect() -> None:
                disconnected.set()

            async def _on_reconnect() -> None:
                reconnected.set()

            pub = MarketTickPublisher(
                config=NatsConnectionConfig(servers=[self.nats.url], reconnect_time_wait=0.1, max_reconnect_attempts=-1)
            )
            await pub.connect(
                on_disconnected=_on_disconnect,
                on_reconnected=_on_reconnect,
            )
            self.assertTrue(pub.client.is_connected)

            self.nats.kill()
            await asyncio.wait_for(disconnected.wait(), timeout=5)
            self.nats.start()
            await asyncio.wait_for(reconnected.wait(), timeout=10)
            self.assertTrue(pub.client.is_connected)
            tick = make_tick()
            subject = await pub.publish(tick)
            self.assertEqual(subject, "market.tick.BTCUSD")

            await pub.close()

        self._run(_test())

    def test_maxpayload_exceeded(self) -> None:
        """Publishing a MarketTick with a payload that exceeds the NATS max size raises PayloadTooLargeError."""

        async def _test() -> None:
            pub = MarketTickPublisher(config=NatsConnectionConfig(servers=[self.nats.url]))
            await pub.connect()

            tick = make_tick()
            oversized_json = "x" * (MAX_PAYLOAD_BYTES + 1)
            with patch.object(MarketTick, "model_dump_json", lambda *_args, **_kwargs: oversized_json):
                with self.assertRaises(PayloadTooLargeError):
                    await pub.publish(tick)

            await pub.close()

        self._run(_test())
