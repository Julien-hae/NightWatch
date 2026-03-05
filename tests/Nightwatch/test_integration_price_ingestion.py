"""Integration tests for the full price ingestion pipeline.

Flow under test: Kraken WS → Parse → MarketTick (pydantic) → NATS publish → subscriber receives.
"""

import asyncio
import json
import time
import unittest
from collections.abc import Coroutine
from decimal import Decimal
from typing import Any

from nats.aio.client import Client as NatsClient

from Nightwatch.kraken_adapter import KrakenAdapter
from Nightwatch.models.market_tick import MarketTick
from Nightwatch.publisher import MarketTickPublisher, NatsServerFixture


class TestPriceIngestionIntegration(unittest.TestCase):
    """Integration tests for the full Kraken → NATS pipeline.

    A single event loop, adapter, and publisher are shared across all tests
    so that the Kraken WebSocket stays on the same loop that runs the
    async test bodies.
    """

    nats: NatsServerFixture
    loop: asyncio.AbstractEventLoop
    adapter: KrakenAdapter
    publisher: MarketTickPublisher

    @classmethod
    def setUpClass(cls) -> None:
        cls.nats = NatsServerFixture()
        cls.nats.start()

        cls.loop = asyncio.new_event_loop()

        cls.adapter = KrakenAdapter()
        cls.loop.run_until_complete(cls.adapter._connect_async())
        cls.loop.run_until_complete(cls.adapter._subscribe_async())

        cls.publisher = MarketTickPublisher(servers=(cls.nats.url,))
        cls.loop.run_until_complete(cls.publisher.connect())

    @classmethod
    def tearDownClass(cls) -> None:
        cls.loop.run_until_complete(cls.adapter._close_async())
        cls.loop.run_until_complete(cls.publisher.close())
        cls.loop.close()
        cls.nats.stop()

    def _run(self, coro: Coroutine[Any, Any, Any]) -> Any:
        """Run *coro* on the shared class-level event loop."""
        return self.loop.run_until_complete(coro)

    def test_publish_tick_from_kraken(self) -> None:
        """Full pipeline: Kraken WS → parse → MarketTick → NATS publish."""

        async def _test() -> None:
            tick = await self.adapter.stream_ticks().__anext__()

            self.assertIsInstance(tick, MarketTick)
            subject = await self.publisher.publish(tick)
            self.assertEqual(subject, "market.tick.BTCUSD")
            self.assertGreater(Decimal(tick.price), 0)

        self._run(_test())

    def test_subscriber_receives_tick_from_kraken(self) -> None:
        """Subscriber on market.tick.BTCUSD receives the exact tick published."""

        async def _test() -> None:
            sub_client = NatsClient()
            await sub_client.connect(servers=[self.nats.url])
            sub = await sub_client.subscribe("market.tick.BTCUSD")

            tick = await self.adapter.stream_ticks().__anext__()
            await self.publisher.publish(tick)

            msg = await asyncio.wait_for(sub.next_msg(), timeout=5)
            payload = json.loads(msg.data)

            self.assertEqual(payload["symbol"], tick.symbol)
            self.assertEqual(Decimal(payload["price"]), Decimal(tick.price))
            self.assertEqual(payload["source"], "Kraken")
            self.assertEqual(payload["schema_version"], 1)

            # Round-trip: reconstruct a MarketTick from the payload
            reconstructed = MarketTick(**payload)
            self.assertEqual(reconstructed.uid, tick.uid)
            self.assertEqual(Decimal(reconstructed.price), Decimal(tick.price))

            await sub_client.drain()

        self._run(_test())

    def test_system_runs_30_seconds_without_crash(self) -> None:
        """The ingestion pipeline processes ticks for 30 s without errors."""

        async def _test() -> None:
            published = 0
            errors: list[str] = []
            deadline = time.monotonic() + 30

            try:
                async for tick in self.adapter.stream_ticks():
                    if time.monotonic() >= deadline:
                        break
                    try:
                        await self.publisher.publish(tick, flush=False)
                        published += 1
                    except Exception as exc:  # noqa: BLE001
                        errors.append(str(exc))
            except asyncio.TimeoutError:
                pass

            self.assertEqual(errors, [], f"Pipeline produced errors: {errors}")
            self.assertGreater(
                published,
                0,
                "Expected at least one tick published in 30 seconds",
            )

        self._run(_test())
