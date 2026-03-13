# mypy: disable-error-code="import-untyped"
"""Integration test for the rolling TickBuffer fed by Kraken adapters over a NATS pub/sub pipeline."""

import asyncio
import os
import unittest
from collections.abc import Coroutine
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from Nightwatch.kraken_adapter import KrakenAdapter
from Nightwatch.models.market_tick import MarketTick
from Nightwatch.models.nats_config import NatsConnectionConfig
from Nightwatch.models.tick_buffer import TickBuffer
from Nightwatch.publisher import MarketTickPublisher
from Nightwatch.subscriber import MarketTickSubscriber
from tests.fixtures.nats_server import NatsServerFixture
from tests.fixtures.tick_factory import make_tick


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

    def test_given_buffer_of_3_when_4_ticks_added_then_oldest_evicted(self) -> None:
        """Test that when more than max_ticks_per_symbol are added, the oldest tick is evicted from the buffer."""
        buffer = TickBuffer(max_ticks_per_symbol=3)
        for i in range(4):
            tick = make_tick(price=Decimal(str(i)), timestamp=datetime.now(timezone.utc))
            buffer.add_tick(tick)
        self.assertEqual(len(buffer.get_ticks("BTC/USD")), 3)
        self.assertEqual(buffer.get_ticks("BTC/USD")[0].price, Decimal("1"))  # oldest evicted

    def test_given_two_symbols_when_ticks_added_then_isolated(self) -> None:
        """Test that ticks for different symbols are stored in separate buffers and do not interfere with each other."""
        btc_tick = make_tick(symbol="BTC/USD")
        eth_tick = make_tick(symbol="ETH/USD")
        self.buffer.add_tick(btc_tick)
        self.buffer.add_tick(eth_tick)
        self.assertIn("BTC/USD", self.buffer.ticks)
        self.assertIn("ETH/USD", self.buffer.ticks)

    def test_given_empty_buffer_when_read_then_empty_dict(self) -> None:
        """Test that a newly initialized TickBuffer has an empty ticks dictionary."""
        buf = TickBuffer()
        self.assertEqual(len(buf.ticks), 0)

    def test_order_preserved(self) -> None:
        """Test that the order of ticks is preserved in the buffer."""
        buf = TickBuffer(max_ticks_per_symbol=5)
        timestamps = [datetime(2024, 1, 1, i, tzinfo=timezone.utc) for i in range(5)]
        for ts in timestamps:
            tick = make_tick(symbol="BTC/USD", timestamp=ts)
            buf.add_tick(tick)
        stored = list(buf.get_ticks("BTC/USD"))
        self.assertEqual([t.timestamp for t in stored], timestamps)
