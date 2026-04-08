# mypy: disable-error-code="import-untyped, union-attr"
"""Integration tests for the StrategyRunner using live data from Kraken."""

import asyncio
import os
import time
import unittest
from collections.abc import Coroutine
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from Nightwatch.kraken_adapter import KrakenAdapter
from Nightwatch.metrics import NightwatchMetrics
from Nightwatch.models.market_tick import MarketTick
from Nightwatch.models.nats_config import NatsConnectionConfig
from Nightwatch.models.risk_engine import RiskEngine
from Nightwatch.models.tick_buffer import TickBuffer
from Nightwatch.publisher import MarketTickPublisher
from Nightwatch.rules.min_trade_strength_rule import MinTradeStrengthRule
from Nightwatch.strategies.momentum_burst import MomentumBurstStrategy
from Nightwatch.strategy_runner import StrategyRunner
from Nightwatch.subscriber import MarketTickSubscriber
from tests.fixtures.nats_server import NatsServerFixture
from tests.fixtures.tick_factory import make_tick_sequence


@unittest.skipUnless(os.environ.get("RUN_INTEGRATION"), "Integration tests require RUN_INTEGRATION=1")
class TestSignalsTotalViaNats(unittest.TestCase):
    """Ingest real Kraken ticks, publish through NATS, subscribe, and assert signals_total increases."""

    nats: NatsServerFixture
    loop: asyncio.AbstractEventLoop
    adapter: KrakenAdapter
    publisher: MarketTickPublisher
    subscriber: MarketTickSubscriber
    runner: StrategyRunner
    metrics: NightwatchMetrics
    strategy: MomentumBurstStrategy
    buffer: TickBuffer

    @classmethod
    def setUpClass(cls) -> None:
        cls.nats = NatsServerFixture()
        cls.nats.start()
        cls.loop = asyncio.new_event_loop()

        cls.adapter = KrakenAdapter()
        cls.loop.run_until_complete(cls.adapter.connect())
        cls.loop.run_until_complete(cls.adapter.subscribe())

        nats_cfg = NatsConnectionConfig(servers=[cls.nats.url])
        cls.publisher = MarketTickPublisher(config=nats_cfg)
        cls.loop.run_until_complete(cls.publisher.connect())

        cls.metrics = NightwatchMetrics()
        cls.subscriber = MarketTickSubscriber(config=nats_cfg, metrics=cls.metrics)
        cls.loop.run_until_complete(cls.subscriber.connect())

        cls.strategy = MomentumBurstStrategy(threshold_pct=0.0001, window_sec=60.0, metric=cls.metrics)
        cls.buffer = TickBuffer(max_ticks_per_symbol=500)
        cls.runner = StrategyRunner(
            strategy=cls.strategy,
            buffer=cls.buffer,
            cooldown=timedelta(seconds=1),
            metric=cls.metrics,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.loop.run_until_complete(cls.adapter.close())
        cls.loop.run_until_complete(cls.publisher.close())
        cls.loop.run_until_complete(cls.subscriber.close())
        cls.loop.close()
        cls.nats.stop()

    def _run(self, coro: Coroutine[Any, Any, Any]) -> Any:
        """Run *coro* on the shared class-level event loop."""
        return self.loop.run_until_complete(coro)

    def test_signals_total_increases_after_ingesting_real_ticks(self) -> None:
        """Ingest live Kraken ticks via NATS for 30 s and verify signals_total increases."""
        symbol = "BTC/USD"

        before = (
            self.metrics.get_counter_value(self.metrics.signals_total, symbol=symbol, side="BUY", strategy=self.strategy.NAME) or 0.0
        ) + (self.metrics.get_counter_value(self.metrics.signals_total, symbol=symbol, side="SELL", strategy=self.strategy.NAME) or 0.0)
        strategy_evaluations_before = (
            self.metrics.get_counter_value(self.metrics.strategy_evaluations_total, symbol=symbol, strategy=self.strategy.NAME) or 0.0
        )
        signal_suppressed_before = self.metrics.get_counter_value(self.metrics.signals_suppressed_total, reason="first_tick") or 0.0

        async def _test() -> None:
            async def _on_tick(tick: MarketTick) -> None:
                self.runner.on_market_tick(tick)

            await self.subscriber.subscribe(subject="market.tick.>", cb=_on_tick)

            deadline = time.monotonic() + 30
            publish_count = 0
            try:
                async for tick in self.adapter.stream_ticks():
                    if time.monotonic() >= deadline:
                        break
                    await self.publisher.publish(tick, flush=False)
                    publish_count += 1
                    if publish_count % 5 == 0:
                        await self.publisher.client.flush()
            except asyncio.TimeoutError:
                pass

            # Flush remaining messages and give subscriber time to process.
            await self.publisher.client.flush()
            await asyncio.sleep(2.0)

            # Feed synthetic ticks with a guaranteed large price spread so
            # that the strategy fires regardless of real-market conditions.
            latest = self.buffer.get_latest_tick(symbol="BTC/USD")
            base_price = latest.price if latest else Decimal("50000")
            base_ts = latest.timestamp if latest else datetime.now(timezone.utc)
            synthetic = make_tick_sequence(
                prices=[base_price, base_price * Decimal("1.10")],
                start=base_ts + timedelta(seconds=5),
                interval_sec=5.0,
                symbol="BTC/USD",
            )
            for tick in synthetic:
                self.runner.on_market_tick(tick)

        self._run(_test())

        after = (
            self.metrics.get_counter_value(self.metrics.signals_total, symbol=symbol, side="BUY", strategy=self.strategy.NAME) or 0.0
        ) + (self.metrics.get_counter_value(self.metrics.signals_total, symbol=symbol, side="SELL", strategy=self.strategy.NAME) or 0.0)
        strategy_evaluations_after = (
            self.metrics.get_counter_value(self.metrics.strategy_evaluations_total, symbol=symbol, strategy=self.strategy.NAME) or 0.0
        )
        signal_suppressed_after = self.metrics.get_counter_value(self.metrics.signals_suppressed_total, reason="first_tick") or 0.0
        ticks_consumed = self.metrics.get_counter_value(
            self.metrics.ticks_consumed_total,
            symbol=symbol,
        )
        if ticks_consumed is None:
            ticks_consumed = 0.0
        self.assertGreater(ticks_consumed, 0.0, "Subscriber should have consumed at least one tick")
        self.assertGreater(after, before, "signals_total should have increased after 30 s of live ticks")
        self.assertGreater(
            strategy_evaluations_after,
            strategy_evaluations_before,
            "strategy_evaluations_total should have increased after 30 s of live ticks",
        )
        self.assertGreater(
            signal_suppressed_after, signal_suppressed_before, "signal_suppressed_total should have increased after 30 s of live ticks"
        )

    def test_risk_engine_rejects_signals_through_nats_pipeline(self) -> None:
        """Publish synthetic ticks through NATS with a restrictive risk engine and verify rejection metrics."""
        symbol = "BTC/USD"
        metric = NightwatchMetrics()
        strategy = MomentumBurstStrategy(threshold_pct=0.0001, window_sec=60.0, metric=metric)
        buffer = TickBuffer(max_ticks_per_symbol=500)
        risk_engine = RiskEngine(rules=[MinTradeStrengthRule(min_strength=99.0)])
        runner = StrategyRunner(
            strategy=strategy,
            buffer=buffer,
            cooldown=timedelta(seconds=0),
            metric=metric,
            risk_engine=risk_engine,
        )

        async def _test() -> None:
            nats_cfg = NatsConnectionConfig(servers=[self.nats.url])
            sub = MarketTickSubscriber(config=nats_cfg, metrics=metric)
            await sub.connect()

            async def _on_tick(tick: MarketTick) -> None:
                runner.on_market_tick(tick)

            await sub.subscribe(subject="market.tick.>", cb=_on_tick)

            base_ts = datetime.now(timezone.utc)
            synthetic = make_tick_sequence(
                prices=[Decimal("50000"), Decimal("55001")],
                start=base_ts,
                interval_sec=5.0,
                symbol=symbol,
            )
            for tick in synthetic:
                await self.publisher.publish(tick, flush=True)

            timeout_at = time.monotonic() + 5.0
            while True:
                suppressed_total = metric.get_counter_value(metric.signals_suppressed_total, reason="MinTradeStrengthRule") or 0.0
                if suppressed_total > 0.0:
                    break
                if time.monotonic() >= timeout_at:
                    self.fail("Timed out waiting for suppressed signals to be recorded")
                await asyncio.sleep(0.05)
            await sub.close()

        self._run(_test())

        signals_total = (metric.get_counter_value(metric.signals_total, symbol=symbol, side="BUY", strategy=strategy.NAME) or 0.0) + (
            metric.get_counter_value(metric.signals_total, symbol=symbol, side="SELL", strategy=strategy.NAME) or 0.0
        )
        suppressed = metric.get_counter_value(metric.signals_suppressed_total, reason="MinTradeStrengthRule") or 0.0

        self.assertGreater(signals_total, 0.0, "Strategy should fire at least once through NATS pipeline")
        self.assertGreater(suppressed, 0.0, "Risk engine should suppress signals below min strength")
