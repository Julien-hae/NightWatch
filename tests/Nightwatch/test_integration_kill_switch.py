# mypy: disable-error-code="import-untyped"
"""Integration tests for the KillSwitch using live data from Kraken."""

import asyncio
import os
import time
import unittest
from collections.abc import Coroutine
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from Nightwatch.messaging.control_event_publisher import ControlEventPublisher
from Nightwatch.messaging.control_event_subscriber import ControlEventSubscriber
from Nightwatch.messaging.publisher import MarketTickPublisher
from Nightwatch.messaging.subscriber import MarketTickSubscriber
from Nightwatch.metrics.metrics import NightwatchMetrics
from Nightwatch.models.bot_control_event import BotControlEvent
from Nightwatch.models.market_tick import MarketTick
from Nightwatch.models.nats_config import NatsConnectionConfig
from Nightwatch.models.tick_buffer import TickBuffer
from Nightwatch.pipeline.kill_switch import KillSwitch
from Nightwatch.pipeline.strategy_runner import StrategyRunner
from Nightwatch.strategies.momentum_burst import MomentumBurstStrategy
from tests.fixtures.nats_server import NatsServerFixture
from tests.fixtures.tick_factory import make_tick_sequence


@unittest.skipUnless(os.environ.get("RUN_INTEGRATION"), "Integration tests require RUN_INTEGRATION=1")
class TestKillSwitchStopsSignalsViaNats(unittest.TestCase):
    """Integration test: publish a kill event via NATS and verify signals are immediately blocked."""

    nats: NatsServerFixture
    loop: asyncio.AbstractEventLoop
    tick_publisher: MarketTickPublisher
    control_publisher: ControlEventPublisher
    control_subscriber: ControlEventSubscriber
    tick_subscriber: MarketTickSubscriber
    metric: NightwatchMetrics
    kill_switch: KillSwitch
    runner: StrategyRunner

    @classmethod
    def setUpClass(cls) -> None:
        cls.nats = NatsServerFixture(jetstream=True)
        cls.nats.start()
        cls.loop = asyncio.new_event_loop()

        nats_cfg = NatsConnectionConfig(servers=[cls.nats.url])

        cls.metric = NightwatchMetrics()

        cls.tick_publisher = MarketTickPublisher(config=nats_cfg)
        cls.loop.run_until_complete(cls.tick_publisher.connect())

        cls.control_publisher = ControlEventPublisher(config=nats_cfg)
        cls.loop.run_until_complete(cls.control_publisher.connect())
        cls.loop.run_until_complete(cls.control_publisher.setup_stream())

        cls.control_subscriber = ControlEventSubscriber(config=nats_cfg)
        cls.loop.run_until_complete(cls.control_subscriber.connect())

        cls.tick_subscriber = MarketTickSubscriber(config=nats_cfg, metrics=cls.metric)
        cls.loop.run_until_complete(cls.tick_subscriber.connect())

        cls.kill_switch = KillSwitch()
        strategy = MomentumBurstStrategy(threshold_pct=0.0001, window_sec=60.0, metric=cls.metric)
        buffer = TickBuffer(max_ticks_per_symbol=500)
        cls.runner = StrategyRunner(
            strategy=strategy,
            buffer=buffer,
            metric=cls.metric,
            kill_switch=cls.kill_switch,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.loop.run_until_complete(cls.tick_publisher.close())
        cls.loop.run_until_complete(cls.control_publisher.close())
        cls.loop.run_until_complete(cls.control_subscriber.close())
        cls.loop.run_until_complete(cls.tick_subscriber.close())
        cls.loop.close()
        cls.nats.stop()

    def _run(self, coro: Coroutine[Any, Any, Any]) -> Any:
        return self.loop.run_until_complete(coro)

    def test_kill_message_stops_signals_immediately(self) -> None:
        """Send a BotControlEvent with kill=True via NATS and verify that subsequent ticks produce no signals."""
        symbol = "BTC/USD"
        base_ts = datetime.now(timezone.utc)

        async def _activate_and_verify() -> None:
            async def _on_control_event(event: BotControlEvent) -> None:
                self.kill_switch.apply(event)

            await self.control_subscriber.subscribe(_on_control_event, durable="kill-switch-test")

            async def _on_tick(tick: MarketTick) -> None:
                self.runner.on_market_tick(tick)

            await self.tick_subscriber.subscribe(subject="market.tick.>", cb=_on_tick)

            pre_stop_ticks = make_tick_sequence(
                prices=[Decimal("50000"), Decimal("55001")],
                start=base_ts,
                interval_sec=5.0,
                symbol=symbol,
            )
            for tick in pre_stop_ticks:
                await self.tick_publisher.publish(tick, flush=True)

            await asyncio.sleep(0.5)

            stop_event = BotControlEvent(kill=True, timestamp=datetime.now(timezone.utc), reason="integration test stop")
            await self.control_publisher.publish(stop_event)

            deadline = time.monotonic() + 5.0
            while self.kill_switch.trading_enabled and time.monotonic() < deadline:
                await asyncio.sleep(0.05)

            self.assertFalse(self.kill_switch.trading_enabled, "Kill switch should be active after receiving stop event")

        self._run(_activate_and_verify())

        async def _assert_ticks_suppressed() -> None:
            suppressed_before = self.metric.get_counter_value(self.metric.signals_suppressed_total, reason="kill_switch") or 0.0

            post_stop_ticks = make_tick_sequence(
                prices=[Decimal("55001"), Decimal("60502")],
                start=datetime.now(timezone.utc),
                interval_sec=5.0,
                symbol=symbol,
            )
            for tick in post_stop_ticks:
                await self.tick_publisher.publish(tick, flush=True)

            await asyncio.sleep(0.5)

            suppressed_after = self.metric.get_counter_value(self.metric.signals_suppressed_total, reason="kill_switch") or 0.0
            self.assertGreater(suppressed_after, suppressed_before, "Ticks published after stop event should be suppressed")

        self._run(_assert_ticks_suppressed())
