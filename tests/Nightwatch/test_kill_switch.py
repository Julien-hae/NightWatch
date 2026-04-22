"""Unit tests for the KillSwitch model in the Nightwatch application."""

import unittest
from datetime import datetime, timezone

from Nightwatch.metrics import NightwatchMetrics
from Nightwatch.models.bot_control_event import BotControlEvent
from Nightwatch.models.kill_switch import KillSwitch
from Nightwatch.models.tick_buffer import TickBuffer
from Nightwatch.strategy_runner import StrategyRunner
from tests.fixtures.test_strategy import NoneStrategy
from tests.fixtures.tick_factory import make_tick


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
