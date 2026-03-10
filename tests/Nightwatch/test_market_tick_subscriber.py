import asyncio
import unittest
from collections.abc import Coroutine
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from Nightwatch.models.market_tick import MarketTick
from Nightwatch.models.nats_connection import NatsConnectionConfig
from Nightwatch.publisher import MarketTickPublisher
from Nightwatch.subscriber import MarketTickSubscriber
from tests.fixtures.nats_server import NatsServerFixture


class TestMarketTickSubscriber(unittest.TestCase):
    """Test suite for the MarketTickSubscriber."""

    nats: NatsServerFixture
    loop: asyncio.AbstractEventLoop
    publisher: MarketTickPublisher
    subscriber: MarketTickSubscriber
    tick: MarketTick

    @classmethod
    def setUpClass(cls) -> None:
        cls.nats = NatsServerFixture()
        cls.nats.start()

        cls.loop = asyncio.new_event_loop()

        cls.subscriber = MarketTickSubscriber(config=NatsConnectionConfig(servers=[cls.nats.url]))
        cls.loop.run_until_complete(cls.subscriber.connect())

        cls.publisher = MarketTickPublisher(config=NatsConnectionConfig(servers=[cls.nats.url]))
        cls.loop.run_until_complete(cls.publisher.connect())

        cls.tick = MarketTick(
            symbol="BTC/USD",
            price=Decimal("50000.0"),
            timestamp=datetime.now(timezone.utc),
            source="test",
            schema_version=1,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.loop.run_until_complete(cls.subscriber.close())
        cls.loop.run_until_complete(cls.publisher.close())
        cls.loop.close()
        cls.nats.stop()

    def _run(self, coro: Coroutine[Any, Any, Any]) -> Any:
        """Run *coro* on the shared class-level event loop."""
        return self.loop.run_until_complete(coro)

    def test_subscriber_receives_published_tick(self) -> None:
        """Test that a MarketTick published by the publisher is received by the subscriber on the correct subject."""

        async def _test() -> None:
            received_tick = None

            async def on_tick(t: MarketTick) -> None:
                nonlocal received_tick
                received_tick = t

            await self.subscriber.subscribe("market.tick.*", on_tick)
            await self.publisher.publish(self.tick)
            await asyncio.sleep(0.1)  # let the callback fire

            self.assertIsNotNone(received_tick)
            if received_tick is not None:
                self.assertIsInstance(received_tick, MarketTick)
                self.assertEqual(received_tick.symbol, self.tick.symbol)
                self.assertEqual(received_tick.price, self.tick.price)
                self.assertEqual(received_tick.uid, self.tick.uid)

        self._run(_test())
