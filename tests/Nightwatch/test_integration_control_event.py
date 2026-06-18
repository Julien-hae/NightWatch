# mypy: disable-error-code="import-untyped"
"""Integration tests for the JetStream control channel (ControlEventPublisher / ControlEventSubscriber)."""

import asyncio
import os
import unittest
from collections.abc import Coroutine
from datetime import datetime, timezone
from typing import Any

from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy
from prometheus_client import CollectorRegistry

from Nightwatch.messaging.control_event_publisher import CONTROL_STREAM_NAME, ControlEventPublisher
from Nightwatch.messaging.control_event_subscriber import ControlEventSubscriber
from Nightwatch.metrics.metrics import NightwatchMetrics
from Nightwatch.models.bot_control_event import BotControlEvent
from Nightwatch.models.nats_config import NatsConnectionConfig
from tests.fixtures.nats_server import NatsServerFixture

_MIN_REDELIVERY_COUNT = 2


def _make_event(*, kill: bool = True, reason: str = "flash crash") -> BotControlEvent:
    return BotControlEvent(kill=kill, timestamp=datetime.now(tz=timezone.utc), reason=reason)


def _counter_value(counter: Any) -> float:
    """Return the current value of a Prometheus counter (reads the *_total sample)."""
    for mf in counter.collect():
        for sample in mf.samples:
            if sample.name.endswith("_total"):
                return float(sample.value)
    return 0.0


@unittest.skipUnless(os.environ.get("RUN_INTEGRATION"), "Integration tests require RUN_INTEGRATION=1")
class TestControlEventIntegration(unittest.TestCase):
    """Integration tests for JetStream control event publish/subscribe."""

    nats: NatsServerFixture
    loop: asyncio.AbstractEventLoop
    publisher: ControlEventPublisher
    subscriber: ControlEventSubscriber
    metric: NightwatchMetrics

    @classmethod
    def setUpClass(cls) -> None:
        cls.nats = NatsServerFixture(jetstream=True)
        cls.nats.start()

        cls.loop = asyncio.new_event_loop()
        registry = CollectorRegistry()
        cls.metric = NightwatchMetrics(registry=registry)

        config = NatsConnectionConfig(servers=[cls.nats.url])

        cls.publisher = ControlEventPublisher(config=config, metrics=cls.metric)
        cls.loop.run_until_complete(cls.publisher.connect())
        cls.loop.run_until_complete(cls.publisher.setup_stream())

        cls.subscriber = ControlEventSubscriber(config=config, metrics=cls.metric)
        cls.loop.run_until_complete(cls.subscriber.connect())

    @classmethod
    def tearDownClass(cls) -> None:
        cls.loop.run_until_complete(cls.publisher.close())
        cls.loop.run_until_complete(cls.subscriber.close())
        cls.loop.close()
        cls.nats.stop()

    def setUp(self) -> None:
        """Purge the CONTROL stream before each test to ensure full isolation."""

        async def _purge() -> None:
            js = self.publisher.client.jetstream()
            await js.purge_stream(CONTROL_STREAM_NAME)

        self.loop.run_until_complete(_purge())

    def _run(self, coro: Coroutine[Any, Any, Any]) -> Any:
        return self.loop.run_until_complete(coro)

    def test_given_connected_publisher_when_publish_then_no_error(self) -> None:
        """Publishing a BotControlEvent via JetStream succeeds without error."""

        async def _test() -> None:
            event = _make_event()
            await self.publisher.publish(event)

        self._run(_test())

    def test_given_published_event_when_subscribed_then_subscriber_receives_it(self) -> None:
        """A BotControlEvent published via JetStream is received by the durable subscriber."""

        async def _test() -> None:
            received: list[BotControlEvent] = []
            received_event = asyncio.Event()

            async def on_event(e: BotControlEvent) -> None:
                received.append(e)
                received_event.set()

            await self.subscriber.subscribe(on_event, durable="ts-rcv-test")

            original = _make_event(reason="integration test receive")
            await self.publisher.publish(original)

            await asyncio.wait_for(received_event.wait(), timeout=5.0)

            self.assertEqual(len(received), 1)
            self.assertEqual(received[0].reason, original.reason)
            self.assertEqual(received[0].kill, original.kill)

        self._run(_test())

    def test_given_published_event_when_not_acknowledged_then_redelivered(self) -> None:
        """A BotControlEvent not acknowledged within ack_wait is redelivered by JetStream."""

        async def _test() -> None:
            delivery_count = 0
            redelivered_event = asyncio.Event()

            config = NatsConnectionConfig(servers=[self.nats.url])

            pub = ControlEventPublisher(config=config)
            await pub.connect()

            sub = ControlEventSubscriber(config=config)
            await sub.connect()

            async def _no_ack_handler(_msg: Any) -> None:
                """Internal callback that intentionally does NOT call ack."""
                nonlocal delivery_count
                delivery_count += 1
                if delivery_count >= _MIN_REDELIVERY_COUNT:
                    redelivered_event.set()

            js = sub.client.jetstream()
            consumer_config = ConsumerConfig(
                durable_name="no-ack-consumer",
                deliver_policy=DeliverPolicy.NEW,
                ack_policy=AckPolicy.EXPLICIT,
                ack_wait=1.0,
                max_deliver=5,
            )

            raw_sub = await js.subscribe(
                subject="control.bot",
                stream=CONTROL_STREAM_NAME,
                config=consumer_config,
                manual_ack=True,
            )

            await pub.publish(_make_event(reason="no-ack redelivery test"))

            deadline = asyncio.get_event_loop().time() + 10.0
            while not redelivered_event.is_set() and asyncio.get_event_loop().time() < deadline:
                try:
                    msg = await asyncio.wait_for(raw_sub.next_msg(timeout=2.0), timeout=3.0)
                    await _no_ack_handler(msg)
                except asyncio.TimeoutError:
                    pass

            await raw_sub.unsubscribe()
            await pub.close()
            await sub.close()

            self.assertTrue(redelivered_event.is_set(), "Expected JetStream to redeliver unacknowledged message")
            self.assertGreaterEqual(delivery_count, 2, "Expected at least 2 deliveries (original + redeliver)")

        self._run(_test())

    def test_given_published_event_when_received_then_metrics_incremented(self) -> None:
        """Publishing and receiving a control event increments the Prometheus counters."""

        async def _test() -> None:
            before_pub = _counter_value(self.metric.control_events_published_total)
            before_rcv = _counter_value(self.metric.control_events_received_total)

            received_event = asyncio.Event()

            async def on_event(_e: BotControlEvent) -> None:
                received_event.set()

            await self.subscriber.subscribe(on_event, durable="ts-metrics-test")
            await self.publisher.publish(_make_event(reason="metrics test"))
            await asyncio.wait_for(received_event.wait(), timeout=5.0)

            self.assertEqual(_counter_value(self.metric.control_events_published_total), before_pub + 1)
            self.assertEqual(_counter_value(self.metric.control_events_received_total), before_rcv + 1)

        self._run(_test())

    def test_kill_on_restart_replays_last_state(self) -> None:
        """Verify DeliverPolicy.LAST recovers state after subscriber restart."""

        async def _test() -> None:
            event = _make_event(reason="restart state recovery test")
            await self.publisher.publish(event)

            received: list[BotControlEvent] = []
            received_event = asyncio.Event()

            async def on_event(e: BotControlEvent) -> None:
                received.append(e)
                received_event.set()

            await self.subscriber.subscribe(on_event, durable="ts-restart-test", deliver_policy=DeliverPolicy.LAST)

            await asyncio.wait_for(received_event.wait(), timeout=5.0)

            self.assertEqual(len(received), 1)
            self.assertEqual(received[0].reason, event.reason)
            self.assertEqual(received[0].kill, event.kill)

        self._run(_test())
