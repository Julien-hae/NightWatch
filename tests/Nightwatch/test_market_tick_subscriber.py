# mypy: disable-error-code="import-untyped"
"""Test suite for the MarketTickSubscriber class, which subscribes to NATS subjects and processes incoming MarketTick messages."""

import asyncio
import os
import unittest
from collections.abc import Coroutine
from typing import Any

from prometheus_client import CollectorRegistry

from Nightwatch.metrics import NightwatchMetrics
from Nightwatch.models.market_tick import MarketTick
from Nightwatch.models.nats_config import NatsConnectionConfig
from Nightwatch.publisher import MarketTickPublisher
from Nightwatch.subscriber import MarketTickSubscriber
from tests.fixtures.nats_server import NatsServerFixture
from tests.fixtures.tick_factory import make_tick


@unittest.skipUnless(os.environ.get("RUN_INTEGRATION"), "Integration tests require RUN_INTEGRATION=1")
class TestMarketTickSubscriber(unittest.TestCase):
    """Test suite for the MarketTickSubscriber."""

    nats: NatsServerFixture
    loop: asyncio.AbstractEventLoop
    publisher: MarketTickPublisher
    subscriber: MarketTickSubscriber
    tick: MarketTick
    metric: NightwatchMetrics

    @classmethod
    def setUpClass(cls) -> None:
        cls.nats = NatsServerFixture()
        cls.nats.start()

        cls.loop = asyncio.new_event_loop()
        registry = CollectorRegistry()
        cls.metric = NightwatchMetrics(registry=registry)

        cls.subscriber = MarketTickSubscriber(
            config=NatsConnectionConfig(servers=[cls.nats.url], reconnect_time_wait=0.1, max_reconnect_attempts=-1),
            metrics=cls.metric,
        )
        cls.loop.run_until_complete(cls.subscriber.connect())

        cls.publisher = MarketTickPublisher(config=NatsConnectionConfig(servers=[cls.nats.url]))
        cls.loop.run_until_complete(cls.publisher.connect())
        cls.tick = make_tick()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.loop.run_until_complete(cls.subscriber.close())
        cls.loop.run_until_complete(cls.publisher.close())
        cls.loop.close()
        cls.nats.stop()

    def _run(self, coro: Coroutine[Any, Any, Any]) -> Any:
        """Run *coro* on the shared class-level event loop."""
        return self.loop.run_until_complete(coro)

    def test_connect_to_nats(self) -> None:
        """Subscriber connects to the NATS server without error."""

        async def _test() -> None:
            await self.subscriber.connect()
            self.assertTrue(self.subscriber.client.is_connected)
            await self.subscriber.close()

        self._run(_test())

    def test_subscriber_receives_published_tick(self) -> None:
        """Test that a MarketTick published by the publisher is received by the subscriber on the correct subject."""

        async def _test() -> None:
            received_tick = None
            received_event = asyncio.Event()

            async def on_tick(t: MarketTick) -> None:
                nonlocal received_tick
                received_tick = t
                received_event.set()

            await self.subscriber.subscribe("market.tick.*", on_tick)
            await self.publisher.publish(self.tick)
            await asyncio.wait_for(received_event.wait(), timeout=1.0)

            self.assertIsNotNone(received_tick)
            if received_tick is not None:
                self.assertIsInstance(received_tick, MarketTick)
                self.assertEqual(received_tick.symbol, self.tick.symbol)
                self.assertEqual(received_tick.price, self.tick.price)
                self.assertEqual(received_tick.uid, self.tick.uid)

        self._run(_test())

    def test_reconnect_after_server_restart(self) -> None:
        """After killing and restarting NATS, the subscriber reconnects and can receive messages again."""

        async def _test() -> None:
            disconnected = asyncio.Event()
            reconnected = asyncio.Event()

            async def _on_disconnect() -> None:
                disconnected.set()

            async def _on_reconnect() -> None:
                reconnected.set()

            await self.subscriber.connect(
                on_disconnected=_on_disconnect,
                on_reconnected=_on_reconnect,
            )
            self.assertTrue(self.subscriber.client.is_connected)

            self.nats.kill()
            await asyncio.wait_for(disconnected.wait(), timeout=5)
            self.nats.start()
            await asyncio.wait_for(reconnected.wait(), timeout=10)

            async def _wait_publisher_reconnect() -> None:
                while not self.publisher.client.is_connected:
                    await asyncio.sleep(0.05)

            await asyncio.wait_for(_wait_publisher_reconnect(), timeout=10)

            self.assertTrue(self.subscriber.client.is_connected)

            received_tick = None

            async def on_tick(t: MarketTick) -> None:
                nonlocal received_tick
                received_tick = t

            await self.subscriber.subscribe("market.tick.*", on_tick)
            await self.publisher.publish(self.tick)
            await asyncio.sleep(0.1)

            self.assertIsNotNone(received_tick)
            self.assertIsInstance(received_tick, MarketTick)

            await self.subscriber.close()

        self._run(_test())

    def test_subscribe_on_bad_data(self) -> None:
        """Test that if the subscriber receives invalid data that cannot be parsed as a MarketTick, it logs an error and increments the parse_errors_total metric, but does not raise an exception."""

        old_value = self.metric.parse_errors_total._value.get()

        async def _test() -> None:
            bad_tick: bytes = b'{"invalid": "message"}'

            async def on_bad_tick(t: bytes) -> None:
                nonlocal bad_tick
                bad_tick = t

            await self.subscriber.subscribe("market.tick.BTCUSD", on_bad_tick)  # type: ignore[arg-type]
            await self.publisher.client.publish("market.tick.BTCUSD", bad_tick)
            await asyncio.sleep(0.1)
            self.assertTrue(self.subscriber.client.is_connected)

            await self.subscriber.close()

        self._run(_test())
        metric_families = list(self.metric.parse_errors_total.collect())
        value = metric_families[0].samples[0].value - old_value
        self.assertEqual(value, 1.0)
