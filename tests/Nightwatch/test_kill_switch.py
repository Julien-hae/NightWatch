# mypy: disable-error-code="import-untyped"
"""Unit tests for the KillSwitch model in the Nightwatch application."""

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from Nightwatch.metrics.metrics import NightwatchMetrics
from Nightwatch.models.bot_control_event import BotControlEvent
from Nightwatch.models.tick_buffer import TickBuffer
from Nightwatch.pipeline.kill_switch import KillSwitch
from Nightwatch.pipeline.risk_engine import RiskEngine
from Nightwatch.pipeline.strategy_runner import StrategyRunner
from Nightwatch.rules.max_signal_per_minute_rule import MaxSignalPerMinuteRule
from Nightwatch.strategies.momentum_burst import MomentumBurstStrategy
from tests.fixtures.test_strategy import AlwaysSignalStrategy, NoneStrategy
from tests.fixtures.tick_factory import feed_ticks, make_tick, make_tick_sequence


class TestKillSwitch(unittest.TestCase):
    """Unit tests for the KillSwitch model."""

    def setUp(self) -> None:
        """Set up common test data."""
        self.none_strategy = NoneStrategy()
        self.momentum_strategy = MomentumBurstStrategy(threshold_pct=10, metric=None)
        self.always_strategy = AlwaysSignalStrategy()
        self.buffer = TickBuffer(max_ticks_per_symbol=30)
        self.metric = NightwatchMetrics()
        self.kill_switch = KillSwitch()

    def test_trading_enabled_by_default(self) -> None:
        """Test that trading is enabled by default."""
        self.assertTrue(self.kill_switch.trading_enabled)

    def test_trading_disabled_by_bot_control_event(self) -> None:
        """Test that applying a BotControlEvent with kill=True disables trading."""
        event = BotControlEvent(kill=True, timestamp=datetime.now(timezone.utc), reason="Emergency stop")
        self.kill_switch.apply(event)
        self.assertFalse(self.kill_switch.trading_enabled)

    def test_trading_activated_by_bot_control_event(self) -> None:
        """Test that applying a BotControlEvent with kill=False enables trading."""
        event = BotControlEvent(kill=False, timestamp=datetime.now(timezone.utc), reason="Resume trading")
        self.kill_switch.apply(event)
        self.assertTrue(self.kill_switch.trading_enabled)

    def test_strategy_runner_respects_kill_switch(self) -> None:
        """Test that the StrategyRunner does not emit signals when the kill switch is active."""
        runner = StrategyRunner(strategy=self.none_strategy, buffer=self.buffer, metric=self.metric, kill_switch=self.kill_switch)

        event = BotControlEvent(kill=True, timestamp=datetime.now(timezone.utc), reason="Testing kill switch")
        self.kill_switch.apply(event)
        before_kill_switch_metric = self.metric.get_counter_value(self.metric.signals_suppressed_total, reason="kill_switch") or 0.0
        tick = make_tick()
        signal = runner.on_market_tick(tick)
        self.assertIsNone(signal)
        after_kill_switch_metric = self.metric.get_counter_value(self.metric.signals_suppressed_total, reason="kill_switch") or 0.0
        self.assertEqual(after_kill_switch_metric, before_kill_switch_metric + 1.0)

    def test_strategy_runner_processes_signals_when_kill_switch_inactive(self) -> None:
        """Test that the StrategyRunner emits signals normally when the kill switch is inactive."""
        risk_engine = RiskEngine(rules=[MaxSignalPerMinuteRule(max_signals_per_min=1000)])
        runner = StrategyRunner(
            strategy=self.momentum_strategy, buffer=self.buffer, metric=self.metric, risk_engine=risk_engine, kill_switch=self.kill_switch
        )

        start_time = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        ticks = make_tick_sequence(
            prices=[Decimal("100"), Decimal("105"), Decimal("115")],
            start=start_time,
            interval_sec=5.0,
            symbol="BTC/USD",
        )
        signal = feed_ticks(runner, ticks)

        self.assertIsNotNone(signal)
        suppressed = self.metric.get_counter_value(self.metric.signals_suppressed_total, reason="kill_switch") or 0.0
        self.assertEqual(suppressed, 0.0)

    def test_kill_switch_idempotent(self) -> None:
        """Test that applying the same BotControlEvent multiple times does not change the state after the first application."""
        true_event = BotControlEvent(kill=True, timestamp=datetime.now(timezone.utc), reason="Idempotent true test")
        false_event = BotControlEvent(kill=False, timestamp=datetime.now(timezone.utc), reason="Idempotent false test")

        self.kill_switch.apply(true_event)
        self.assertFalse(self.kill_switch.trading_enabled)
        self.kill_switch.apply(true_event)
        self.assertFalse(self.kill_switch.trading_enabled)

        self.kill_switch.apply(false_event)
        self.assertTrue(self.kill_switch.trading_enabled)
        self.kill_switch.apply(false_event)
        self.assertTrue(self.kill_switch.trading_enabled)

    def test_resume_after_kill_emits_signal_only_on_fresh_ticks(self) -> None:
        """Given kill=ON ticks ignored, when kill=OFF, then signal requires N new ticks."""
        risk_engine = RiskEngine(rules=[MaxSignalPerMinuteRule(max_signals_per_min=1000)])
        runner = StrategyRunner(
            strategy=self.always_strategy, buffer=self.buffer, metric=self.metric, risk_engine=risk_engine, kill_switch=self.kill_switch
        )

        kill_event = BotControlEvent(kill=True, timestamp=datetime.now(timezone.utc), reason="Testing kill switch")
        self.kill_switch.apply(kill_event)

        for _ in range(5):
            tick = make_tick()
            signal = runner.on_market_tick(tick)
            self.assertIsNone(signal)

        resume_event = BotControlEvent(kill=False, timestamp=datetime.now(timezone.utc), reason="Resuming trading")
        self.kill_switch.apply(resume_event)

        tick_after_resume = make_tick()
        signal_after_resume = runner.on_market_tick(tick_after_resume)
        self.assertIsNone(signal_after_resume)

        next_tick = make_tick()
        signal_next_tick = runner.on_market_tick(next_tick)
        self.assertIsNotNone(signal_next_tick)

    def test_not_ready_suppresses_signals(self) -> None:
        """Test that StrategyRunner suppresses all signals when the kill switch is not ready."""
        kill_switch = KillSwitch(ready=False, metrics=self.metric)
        runner = StrategyRunner(strategy=self.momentum_strategy, buffer=self.buffer, metric=self.metric, kill_switch=kill_switch)

        tick = make_tick()
        signal = runner.on_market_tick(tick)
        self.assertIsNone(signal)

        suppressed = self.metric.get_counter_value(self.metric.signals_suppressed_total, reason="kill_switch_not_ready") or 0.0
        self.assertEqual(suppressed, 1.0)

    def test_mark_ready_allows_signals(self) -> None:
        """Test that after mark_ready(), signals flow normally."""
        kill_switch = KillSwitch(ready=False, metrics=self.metric)
        runner = StrategyRunner(strategy=self.always_strategy, buffer=self.buffer, metric=self.metric, kill_switch=kill_switch)

        tick1 = make_tick()
        self.assertIsNone(runner.on_market_tick(tick1))

        kill_switch.mark_ready()
        self.assertTrue(kill_switch.ready)

        tick2 = make_tick()
        runner.on_market_tick(tick2)  # first tick after buffer clear — suppressed
        tick3 = make_tick()
        signal = runner.on_market_tick(tick3)
        self.assertIsNotNone(signal)

    def test_not_ready_with_kill_true_restores_killed_state(self) -> None:
        """Test that applying a kill event while not-ready restores killed state, then marking ready keeps it killed."""
        kill_switch = KillSwitch(ready=False, metrics=self.metric)
        runner = StrategyRunner(strategy=self.momentum_strategy, buffer=self.buffer, metric=self.metric, kill_switch=kill_switch)

        kill_event = BotControlEvent(kill=True, timestamp=datetime.now(timezone.utc), reason="Restored from backlog")
        kill_switch.apply(kill_event)
        kill_switch.mark_ready()

        self.assertTrue(kill_switch.ready)
        self.assertFalse(kill_switch.trading_enabled)

        tick = make_tick()
        signal = runner.on_market_tick(tick)
        self.assertIsNone(signal)
        suppressed = self.metric.get_counter_value(self.metric.signals_suppressed_total, reason="kill_switch") or 0.0
        self.assertGreater(suppressed, 0.0)

    def test_kill_switch_off_then_on_then_off(self) -> None:
        """Test that toggling the kill switch off, then on, then off again works as expected and block/allows signal on each state."""
        kill_switch = KillSwitch(ready=False, metrics=self.metric)
        runner = StrategyRunner(strategy=self.always_strategy, buffer=self.buffer, metric=self.metric, kill_switch=kill_switch)

        event_off = BotControlEvent(kill=True, timestamp=datetime.now(timezone.utc), reason="Kill switch off")
        kill_switch.apply(event_off)
        self.assertFalse(kill_switch.trading_enabled)
        kill_switch.mark_ready()

        tick_off_1 = make_tick()
        self.assertIsNone(runner.on_market_tick(tick_off_1))

        event_on = BotControlEvent(kill=False, timestamp=datetime.now(timezone.utc), reason="Kill switch on")
        kill_switch.apply(event_on)
        self.assertTrue(kill_switch.trading_enabled)

        tick_on = make_tick()
        self.assertIsNone(runner.on_market_tick(tick_on))
        tick_on_2 = make_tick()
        self.assertIsNotNone(runner.on_market_tick(tick_on_2))

        event_off_again = BotControlEvent(kill=True, timestamp=datetime.now(timezone.utc), reason="Kill switch off")
        kill_switch.apply(event_off_again)
        self.assertFalse(kill_switch.trading_enabled)

        tick_off_2 = make_tick()
        self.assertIsNone(runner.on_market_tick(tick_off_2))

        suppressed = self.metric.get_counter_value(self.metric.signals_suppressed_total, reason="kill_switch") or 0.0
        self.assertEqual(suppressed, 2.0)

    def test_gauges_reflect_initial_state_on_construction(self) -> None:
        """Both kill-switch gauges must show the real starting state immediately, not just after the first event."""
        ready_switch = KillSwitch(metrics=self.metric)
        self.assertEqual(self.metric.kill_switch_trading_enabled._value.get(), 1.0)
        self.assertEqual(self.metric.kill_switch_ready._value.get(), 1.0)
        self.assertTrue(ready_switch.trading_enabled)  # sanity: matches the gauge

        not_ready_metric = NightwatchMetrics()
        KillSwitch(metrics=not_ready_metric, ready=False)
        self.assertEqual(not_ready_metric.kill_switch_ready._value.get(), 0.0)

    def test_mark_ready_sets_the_ready_gauge(self) -> None:
        kill_switch = KillSwitch(metrics=self.metric, ready=False)
        self.assertEqual(self.metric.kill_switch_ready._value.get(), 0.0)

        kill_switch.mark_ready()

        self.assertEqual(self.metric.kill_switch_ready._value.get(), 1.0)

    def test_apply_sets_the_trading_enabled_gauge(self) -> None:
        kill_switch = KillSwitch(metrics=self.metric)

        kill_switch.apply(BotControlEvent(kill=True, timestamp=datetime.now(timezone.utc), reason="gauge test"))
        self.assertEqual(self.metric.kill_switch_trading_enabled._value.get(), 0.0)

        kill_switch.apply(BotControlEvent(kill=False, timestamp=datetime.now(timezone.utc), reason="gauge test"))
        self.assertEqual(self.metric.kill_switch_trading_enabled._value.get(), 1.0)
