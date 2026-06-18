# mypy: disable-error-code="import-untyped"
"""Integration test for the rolling TickBuffer fed by Kraken adapters over a NATS pub/sub pipeline."""

import asyncio
import os
import unittest
from collections.abc import Coroutine
from typing import Any

from Nightwatch.adapters.kraken_adapter import KrakenAdapter
from Nightwatch.messaging.publisher import MarketTickPublisher
from Nightwatch.messaging.subscriber import MarketTickSubscriber
from Nightwatch.models.market_tick import MarketTick
from Nightwatch.models.nats_config import NatsConnectionConfig
from Nightwatch.models.tick_buffer import TickBuffer
from tests.fixtures.nats_server import NatsServerFixture


@unittest.skipUnless(os.environ.get("RUN_INTEGRATION"), "Integration tests require RUN_INTEGRATION=1")
class TestTickBuffer(unittest.TestCase):
    """Test suite for the RollingTickBuffer."""

    nats: NatsServerFixture
    loop: asyncio.AbstractEventLoop
    publisher: MarketTickPublisher
    subscriber: MarketTickSubscriber
    btc_adapter: KrakenAdapter
    eth_adapter: KrakenAdapter
    buffer: TickBuffer

    @classmethod
    def setUpClass(cls) -> None:
        cls.nats = NatsServerFixture()
        cls.nats.start()

        cls.loop = asyncio.new_event_loop()

        cls.btc_adapter = KrakenAdapter(symbol="BTC/USD")
        cls.loop.run_until_complete(cls.btc_adapter.connect())
        cls.loop.run_until_complete(cls.btc_adapter.subscribe())

        cls.eth_adapter = KrakenAdapter(symbol="ETH/USD")
        cls.loop.run_until_complete(cls.eth_adapter.connect())
        cls.loop.run_until_complete(cls.eth_adapter.subscribe())

        cls.subscriber = MarketTickSubscriber(
            config=NatsConnectionConfig(servers=[cls.nats.url], reconnect_time_wait=0.1, max_reconnect_attempts=-1)
        )
        cls.loop.run_until_complete(cls.subscriber.connect())

        cls.publisher = MarketTickPublisher(config=NatsConnectionConfig(servers=[cls.nats.url]))
        cls.loop.run_until_complete(cls.publisher.connect())

        cls.buffer = TickBuffer()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.loop.run_until_complete(cls.btc_adapter.close())
        cls.loop.run_until_complete(cls.eth_adapter.close())
        cls.loop.run_until_complete(cls.subscriber.close())
        cls.loop.run_until_complete(cls.publisher.close())
        cls.loop.close()
        cls.nats.stop()

    def _run(self, coro: Coroutine[Any, Any, Any]) -> Any:
        """Run *coro* on the shared class-level event loop."""
        return self.loop.run_until_complete(coro)

    def test_rolling_tick_buffer(self) -> None:
        """Test that the RollingTickBuffer correctly maintains the most recent tick for each symbol."""

        async def _test() -> None:
            async def on_tick(t: MarketTick) -> None:
                self.buffer.add_tick(t)

            await self.subscriber.subscribe("market.tick.*", on_tick)

            async def stream_and_publish(adapter: KrakenAdapter) -> None:
                async for tick in adapter.stream_ticks():
                    await self.publisher.publish(tick)

            tasks = [
                asyncio.create_task(stream_and_publish(self.btc_adapter)),
                asyncio.create_task(stream_and_publish(self.eth_adapter)),
            ]

            await asyncio.sleep(30)

            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

            self.assertIn("BTC/USD", self.buffer.ticks)
            self.assertIn("ETH/USD", self.buffer.ticks)
            self.assertLessEqual(len(self.buffer.get_ticks("BTC/USD")), self.buffer.max_ticks_per_symbol)
            self.assertLessEqual(len(self.buffer.get_ticks("ETH/USD")), self.buffer.max_ticks_per_symbol)
            self.assertTrue(
                all(
                    earlier.timestamp <= later.timestamp
                    for earlier, later in zip(self.buffer.get_ticks("ETH/USD"), list(self.buffer.get_ticks("ETH/USD"))[1:])
                )
            )
            self.assertTrue(
                all(
                    earlier.timestamp <= later.timestamp
                    for earlier, later in zip(self.buffer.get_ticks("BTC/USD"), list(self.buffer.get_ticks("BTC/USD"))[1:])
                )
            )

        self._run(_test())
