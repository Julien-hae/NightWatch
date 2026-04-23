# mypy: disable-error-code="import-untyped"
"""Unit tests for the KillSwitch model in the Nightwatch application."""

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from Nightwatch.kill_switch import KillSwitch
from Nightwatch.metrics import NightwatchMetrics
from Nightwatch.models.bot_control_event import BotControlEvent
from Nightwatch.models.tick_buffer import TickBuffer
from Nightwatch.risk_engine import RiskEngine
from Nightwatch.rules.max_signal_per_minute_rule import MaxSignalPerMinuteRule
from Nightwatch.strategies.momentum_burst import MomentumBurstStrategy
from Nightwatch.strategy_runner import StrategyRunner
from tests.fixtures.test_strategy import AlwaysSignalStrategy, NoneStrategy
from tests.fixtures.tick_factory import feed_ticks, make_tick, make_tick_sequence


class TestKillSwitch(unittest.TestCase):
    """Unit tests for the KillSwitch model."""

    def test_trading_enabled_by_default(self) -> None:
        """Test that trading is enabled by default."""
        kill_switch = KillSwitch()
        self.assertTrue(kill_switch.trading_enabled)

    def test_trading_disabled_by_bot_control_event(self) -> None:
        """Test that applying a BotControlEvent with kill=True disables trading."""
        kill_switch = KillSwitch()
        event = BotControlEvent(kill=True, timestamp=datetime.now(timezone.utc), reason="Emergency stop")
        kill_switch.apply(event)
        self.assertFalse(kill_switch.trading_enabled)

    def test_trading_activated_by_bot_control_event(self) -> None:
        """Test that applying a BotControlEvent with kill=False enables trading."""
        kill_switch = KillSwitch(trading_enabled=False)
        event = BotControlEvent(kill=False, timestamp=datetime.now(timezone.utc), reason="Resume trading")
        kill_switch.apply(event)
        self.assertTrue(kill_switch.trading_enabled)

    def test_strategy_runner_respects_kill_switch(self) -> None:
        """Test that the StrategyRunner does not emit signals when the kill switch is active."""
        strategy = NoneStrategy()
        buffer = TickBuffer()
        metric = NightwatchMetrics()
        kill_switch = KillSwitch()
        runner = StrategyRunner(strategy=strategy, buffer=buffer, metric=metric, kill_switch=kill_switch)

        event = BotControlEvent(kill=True, timestamp=datetime.now(timezone.utc), reason="Testing kill switch")
        kill_switch.apply(event)
        before_kill_switch_metric = metric.get_counter_value(metric.signals_suppressed_total, reason="kill_switch") or 0.0
        tick = make_tick()
        signal = runner.on_market_tick(tick)
        self.assertIsNone(signal)
        after_kill_switch_metric = metric.get_counter_value(metric.signals_suppressed_total, reason="kill_switch") or 0.0
        self.assertEqual(after_kill_switch_metric, before_kill_switch_metric + 1.0)

    def test_strategy_runner_processes_signals_when_kill_switch_inactive(self) -> None:
        """Test that the StrategyRunner emits signals normally when the kill switch is inactive."""
        metric = NightwatchMetrics()
        strategy = MomentumBurstStrategy(threshold_pct=10, metric=metric)
        buffer = TickBuffer(max_ticks_per_symbol=30)
        risk_engine = RiskEngine(rules=[MaxSignalPerMinuteRule(max_signals_per_min=1000)])
        kill_switch = KillSwitch()  # trading_enabled=True by default
        runner = StrategyRunner(strategy=strategy, buffer=buffer, metric=metric, risk_engine=risk_engine, kill_switch=kill_switch)

        start_time = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        ticks = make_tick_sequence(
            prices=[Decimal("100"), Decimal("105"), Decimal("115")],
            start=start_time,
            interval_sec=5.0,
            symbol="BTC/USD",
        )
        signal = feed_ticks(runner, ticks)

        self.assertIsNotNone(signal)
        suppressed = metric.get_counter_value(metric.signals_suppressed_total, reason="kill_switch") or 0.0
        self.assertEqual(suppressed, 0.0)

    def test_kill_switch_idempotent(self) -> None:
        """Test that applying the same BotControlEvent multiple times does not change the state after the first application."""
        kill_switch = KillSwitch()
        event = BotControlEvent(kill=True, timestamp=datetime.now(timezone.utc), reason="Idempotent test")
        kill_switch.apply(event)
        self.assertFalse(kill_switch.trading_enabled)
        kill_switch.apply(event)  # Applying the same event again should not change the state
        self.assertFalse(kill_switch.trading_enabled)

    def test_resume_after_kill_emits_signal_only_on_fresh_ticks(self) -> None:
        """Test that resuming trading after a kill switch event only allows signals to be emitted on new ticks, not old ones."""
        strategy = AlwaysSignalStrategy()
        buffer = TickBuffer()
        metric = NightwatchMetrics()
        kill_switch = KillSwitch()
        runner = StrategyRunner(strategy=strategy, buffer=buffer, metric=metric, kill_switch=kill_switch)

        # Apply kill switch
        kill_event = BotControlEvent(kill=True, timestamp=datetime.now(timezone.utc), reason="Testing resume")
        kill_switch.apply(kill_event)

        # Feed a tick while kill switch is active (should be suppressed)
        tick1 = make_tick()
        signal1 = runner.on_market_tick(tick1)
        self.assertIsNone(signal1)
        suppressed_after_kill = metric.get_counter_value(metric.signals_suppressed_total, reason="kill_switch") or 0.0
        self.assertEqual(suppressed_after_kill, 1.0)

        # Resume trading
        resume_event = BotControlEvent(kill=False, timestamp=datetime.now(timezone.utc), reason="Resuming trading")
        kill_switch.apply(resume_event)

        # Feed the same tick again (should not emit signal since it's not fresh)
        signal2 = runner.on_market_tick(tick1)
        self.assertIsNone(signal2)

        # Feed a new tick (should be processed normally)
        tick2 = make_tick(timestamp=tick1.timestamp + timedelta(seconds=10))
        signal3 = runner.on_market_tick(tick2)
        self.assertIsNotNone(signal3)
