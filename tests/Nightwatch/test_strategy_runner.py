# mypy: disable-error-code="import-untyped, union-attr"
"""Unit tests for the StrategyRunner class."""

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from Nightwatch.metrics.metrics import NightwatchMetrics
from Nightwatch.models.bot_control_event import BotControlEvent
from Nightwatch.models.tick_buffer import TickBuffer
from Nightwatch.pipeline.kill_switch import KillSwitch
from Nightwatch.pipeline.risk_engine import RiskEngine
from Nightwatch.pipeline.strategy_runner import StrategyRunner
from Nightwatch.rules.cooldown_rule import CooldownRule
from Nightwatch.rules.max_signal_per_minute_rule import MaxSignalPerMinuteRule
from Nightwatch.rules.min_trade_strength_rule import MinTradeStrengthRule
from Nightwatch.strategies.momentum_burst import MomentumBurstStrategy
from tests.fixtures.tick_factory import feed_ticks, make_tick, make_tick_sequence


class TestStrategyRunner(unittest.TestCase):
    """Unit tests for the StrategyRunner class."""

    def setUp(self) -> None:
        self._metric = NightwatchMetrics()
        self.__strategy = MomentumBurstStrategy(threshold_pct=10, metric=self._metric)
        self.__buffer = TickBuffer(max_ticks_per_symbol=30)
        self.risk_engine = RiskEngine(rules=[MaxSignalPerMinuteRule(max_signals_per_min=1000)])
        self.runner = StrategyRunner(
            strategy=self.__strategy,
            buffer=self.__buffer,
            metric=self._metric,
            risk_engine=self.risk_engine,
        )
        self.start_time = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)

    def test_emit_signal_on_rising_sequence(self) -> None:
        """Test that a rising sequence of ticks generates a buy signal."""
        rising_ticks = make_tick_sequence(
            prices=[Decimal("100"), Decimal("105"), Decimal("115")], start=self.start_time, interval_sec=5.0, symbol="BTC/USD"
        )
        signal = feed_ticks(self.runner, rising_ticks)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.side.value, "BUY")  # type: ignore[union-attr]

    def test_emit_no_signal_on_falling_sequence(self) -> None:
        """Test that an outside threshold sequence of ticks does not generate a signal."""
        failing_ticks = make_tick_sequence(
            prices=[Decimal("100"), Decimal("95"), Decimal("105")], start=self.start_time, interval_sec=5.0, symbol="BTC/USD"
        )
        signal = feed_ticks(self.runner, failing_ticks)
        self.assertIsNone(signal)

    def test_integration_with_momentum_burst_strategy(self) -> None:
        """Test that the StrategyRunner correctly integrates with the MomentumBurstStrategy."""

        ticks = make_tick_sequence(
            prices=[Decimal("100"), Decimal("105"), Decimal("115")], start=self.start_time, interval_sec=5.0, symbol="BTC/USD"
        )
        signal = feed_ticks(self.runner, ticks)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.side.value, "BUY")  # type: ignore[union-attr]

    def test_logging_contains_required_fields(self) -> None:
        """Test that the logs contain the required fields when emitting signals."""
        with self.assertLogs("Nightwatch.pipeline.strategy_runner", level="DEBUG") as log:
            ticks = make_tick_sequence(
                prices=[Decimal("100"), Decimal("105"), Decimal("115")], start=self.start_time, interval_sec=5.0, symbol="BTC/USD"
            )
            for tick in ticks:
                self.runner.on_market_tick(tick)

        log_output = "\n".join(log.output)
        self.assertIn("event", log_output)
        self.assertIn("signal_id", log_output)
        self.assertIn("symbol", log_output)
        self.assertIn("side", log_output)
        self.assertIn("strategy", log_output)
        self.assertIn("delta_pct", log_output)
        self.assertIn("window_sec", log_output)
        self.assertIn("threshold_pct", log_output)

    def test_signals_total(self) -> None:
        """Test that the counter signals_total is incremented correctly."""
        initial_evaluations = (
            self._metric.get_counter_value(self._metric.signals_total, symbol="BTC/USD", side="BUY", strategy=self.__strategy.NAME) or 0
        )
        ticks = make_tick_sequence(
            prices=[Decimal("100"), Decimal("115"), Decimal("135")], start=self.start_time, interval_sec=10.0, symbol="BTC/USD"
        )
        feed_ticks(self.runner, ticks)
        final_evaluations = (
            self._metric.get_counter_value(self._metric.signals_total, symbol="BTC/USD", side="BUY", strategy=self.__strategy.NAME) or 0
        )
        self.assertEqual(final_evaluations, initial_evaluations + 1)

    def test_risk_engine_rejects_low_strength_signal(self) -> None:
        """When MinTradeStrengthRule min_strength exceeds the signal strength, on_market_tick returns None."""
        metric = NightwatchMetrics()
        strategy = MomentumBurstStrategy(threshold_pct=10, metric=metric)
        buffer = TickBuffer(max_ticks_per_symbol=30)
        risk_engine = RiskEngine(rules=[MinTradeStrengthRule(min_strength=50.0)])
        runner = StrategyRunner(strategy=strategy, buffer=buffer, metric=metric, risk_engine=risk_engine)

        ticks = make_tick_sequence(
            prices=[Decimal("100"), Decimal("105"), Decimal("115")], start=self.start_time, interval_sec=5.0, symbol="BTC/USD"
        )
        signal = feed_ticks(runner, ticks)
        self.assertIsNone(signal)

    def test_risk_engine_rejection_increments_suppressed_metric_with_reason(self) -> None:
        """When the risk engine rejects, signals_suppressed_total is incremented with the rule's reason."""
        metric = NightwatchMetrics()
        strategy = MomentumBurstStrategy(threshold_pct=10, metric=metric)
        buffer = TickBuffer(max_ticks_per_symbol=30)
        risk_engine = RiskEngine(rules=[MinTradeStrengthRule(min_strength=50.0)])
        runner = StrategyRunner(strategy=strategy, buffer=buffer, metric=metric, risk_engine=risk_engine)

        ticks = make_tick_sequence(
            prices=[Decimal("100"), Decimal("105"), Decimal("115")], start=self.start_time, interval_sec=5.0, symbol="BTC/USD"
        )
        feed_ticks(runner, ticks)

        suppressed = metric.get_counter_value(metric.signals_suppressed_total, reason="MinTradeStrengthRule") or 0.0
        self.assertEqual(suppressed, 1.0)
        signals = metric.get_counter_value(metric.signals_total, symbol="BTC/USD", side="BUY", strategy=strategy.NAME) or 0.0
        self.assertEqual(signals, 1.0)

    def test_risk_engine_rejection_logs_rule_and_reason(self) -> None:
        """When the risk engine rejects a signal, the log contains the rule name and reason."""
        metric = NightwatchMetrics()
        strategy = MomentumBurstStrategy(threshold_pct=10, metric=metric)
        buffer = TickBuffer(max_ticks_per_symbol=30)
        risk_engine = RiskEngine(rules=[MinTradeStrengthRule(min_strength=50.0)])
        runner = StrategyRunner(strategy=strategy, buffer=buffer, metric=metric, risk_engine=risk_engine)

        with self.assertLogs("Nightwatch.pipeline.strategy_runner", level="INFO") as log:
            ticks = make_tick_sequence(
                prices=[Decimal("100"), Decimal("105"), Decimal("115")], start=self.start_time, interval_sec=5.0, symbol="BTC/USD"
            )
            for tick in ticks:
                runner.on_market_tick(tick)

        log_output = "\n".join(log.output)
        self.assertIn("rejected by rule", log_output)
        self.assertIn("MinTradeStrengthRule", log_output)
        self.assertIn("Trade strength below minimum", log_output)

    def test_risk_engine_max_signals_per_minute_blocks_excess(self) -> None:
        """MaxSignalPerMinuteRule with max=1 allows the first signal but rejects the second."""
        metric = NightwatchMetrics()
        strategy = MomentumBurstStrategy(threshold_pct=10, window_sec=60, metric=metric)
        buffer = TickBuffer(max_ticks_per_symbol=30)
        risk_engine = RiskEngine(rules=[MaxSignalPerMinuteRule(max_signals_per_min=1)])
        runner = StrategyRunner(strategy=strategy, buffer=buffer, metric=metric, risk_engine=risk_engine)

        ticks = make_tick_sequence(prices=[Decimal("100"), Decimal("115")], start=self.start_time, interval_sec=5.0, symbol="BTC/USD")
        signal1 = feed_ticks(runner, ticks)
        self.assertIsNotNone(signal1)

        tick2 = make_tick(price=Decimal("135"), timestamp=self.start_time + timedelta(seconds=10))
        signal2 = runner.on_market_tick(tick2)
        self.assertIsNone(signal2)

        suppressed = metric.get_counter_value(metric.signals_suppressed_total, reason="MaxSignalPerMinuteRule") or 0.0
        self.assertEqual(suppressed, 1.0)

    def test_risk_engine_allows_signal_when_rules_pass(self) -> None:
        """When all risk rules pass, the signal is returned normally."""
        metric = NightwatchMetrics()
        strategy = MomentumBurstStrategy(threshold_pct=10, metric=metric)
        buffer = TickBuffer(max_ticks_per_symbol=30)
        risk_engine = RiskEngine(rules=[MinTradeStrengthRule(min_strength=1.0), MaxSignalPerMinuteRule(max_signals_per_min=1000)])
        runner = StrategyRunner(strategy=strategy, buffer=buffer, metric=metric, risk_engine=risk_engine)

        ticks = make_tick_sequence(
            prices=[Decimal("100"), Decimal("105"), Decimal("115")], start=self.start_time, interval_sec=5.0, symbol="BTC/USD"
        )
        signal = feed_ticks(runner, ticks)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.side.value, "BUY")  # type: ignore[union-attr]

        suppressed = metric.get_counter_value(metric.signals_suppressed_total, reason="MinTradeStrengthRule") or 0.0
        self.assertEqual(suppressed, 0.0)

    def test_default_risk_engine_rejects_low_strength(self) -> None:
        """StrategyRunner without explicit risk_engine uses default RiskEngine, which rejects low-strength signals."""
        metric = NightwatchMetrics()
        strategy = MomentumBurstStrategy(threshold_pct=1, window_sec=60, metric=metric)
        buffer = TickBuffer(max_ticks_per_symbol=30)
        runner = StrategyRunner(strategy=strategy, buffer=buffer, metric=metric)

        ticks = make_tick_sequence(prices=[Decimal("100"), Decimal("105")], start=self.start_time, interval_sec=5.0, symbol="BTC/USD")
        signal = feed_ticks(runner, ticks)
        self.assertIsNone(signal)

        suppressed = metric.get_counter_value(metric.signals_suppressed_total, reason="MinTradeStrengthRule") or 0.0
        self.assertEqual(suppressed, 1.0)

    def test_risk_engine_multiple_rules_first_rejection_wins(self) -> None:
        """When multiple rules could reject, the first rejecting rule determines the reason."""
        metric = NightwatchMetrics()
        strategy = MomentumBurstStrategy(threshold_pct=10, window_sec=60, metric=metric)
        buffer = TickBuffer(max_ticks_per_symbol=30)
        risk_engine = RiskEngine(rules=[CooldownRule(cooldown_seconds=999), MinTradeStrengthRule(min_strength=50.0)])
        runner = StrategyRunner(strategy=strategy, buffer=buffer, metric=metric, risk_engine=risk_engine)

        ticks = make_tick_sequence(prices=[Decimal("100"), Decimal("155")], start=self.start_time, interval_sec=5.0, symbol="BTC/USD")
        signal1 = feed_ticks(runner, ticks)
        self.assertIsNotNone(signal1)
        self.assertEqual(metric.get_counter_value(metric.signals_suppressed_total, reason="MinTradeStrengthRule") or 0.0, 0.0)

        tick2 = make_tick(price=Decimal("172"), timestamp=self.start_time + timedelta(seconds=65))
        runner.on_market_tick(tick2)
        cooldown_suppressed = metric.get_counter_value(metric.signals_suppressed_total, reason="CooldownRule") or 0.0
        self.assertEqual(cooldown_suppressed, 1.0)
        min_suppressed_after = metric.get_counter_value(metric.signals_suppressed_total, reason="MinTradeStrengthRule") or 0.0
        self.assertEqual(min_suppressed_after, 0.0)

    def test_buffer_not_contaminated_after_resume(self) -> None:
        """After a pause and resume, the buffer should not contain stale ticks that could trigger false signals."""
        metric = NightwatchMetrics()
        strategy = MomentumBurstStrategy(threshold_pct=10, window_sec=60, metric=metric)
        buffer = TickBuffer(max_ticks_per_symbol=30)
        risk_engine = RiskEngine(rules=[MinTradeStrengthRule(min_strength=1.0)])
        runner = StrategyRunner(strategy=strategy, buffer=buffer, metric=metric, risk_engine=risk_engine)

        ticks1 = make_tick_sequence(
            prices=[Decimal("100"), Decimal("105"), Decimal("115")], start=self.start_time, interval_sec=5.0, symbol="BTC/USD"
        )
        signal1 = feed_ticks(runner, ticks1)
        self.assertIsNotNone(signal1)

        buffer.clear_ticks("BTC/USD")
        pause_duration = timedelta(seconds=120)
        resume_time = self.start_time + pause_duration

        ticks2 = make_tick_sequence(
            prices=[Decimal("200"), Decimal("210"), Decimal("230")], start=resume_time, interval_sec=5.0, symbol="BTC/USD"
        )
        signal2 = feed_ticks(runner, ticks2)
        self.assertIsNotNone(signal2)

    def test_logging_does_not_fire_on_rejected_signal(self) -> None:
        """When the risk engine rejects a signal, the detailed signal log should not be emitted."""
        metric = NightwatchMetrics()
        strategy = MomentumBurstStrategy(threshold_pct=10, metric=metric)
        buffer = TickBuffer(max_ticks_per_symbol=30)
        risk_engine = RiskEngine(rules=[MinTradeStrengthRule(min_strength=50.0)])
        runner = StrategyRunner(strategy=strategy, buffer=buffer, metric=metric, risk_engine=risk_engine)

        with self.assertLogs("Nightwatch.pipeline.strategy_runner", level="INFO") as log:
            ticks = make_tick_sequence(
                prices=[Decimal("100"), Decimal("105"), Decimal("115")], start=self.start_time, interval_sec=5.0, symbol="BTC/USD"
            )
            for tick in ticks:
                runner.on_market_tick(tick)

        log_output = "\n".join(log.output)
        self.assertIn("rejected by rule", log_output)
        self.assertNotIn('"event": "signal"', log_output)

    def test_strategy_runner_returns_none_when_strategy_returns_none(self) -> None:
        """If the strategy returns None, the StrategyRunner should also return None and not log a signal."""
        metric = NightwatchMetrics()
        strategy = MomentumBurstStrategy(threshold_pct=10, metric=metric)
        buffer = TickBuffer(max_ticks_per_symbol=30)
        risk_engine = RiskEngine(rules=[MinTradeStrengthRule(min_strength=1.0)])
        runner = StrategyRunner(strategy=strategy, buffer=buffer, metric=metric, risk_engine=risk_engine)

        ticks = make_tick_sequence(
            prices=[Decimal("100"), Decimal("101"), Decimal("102")], start=self.start_time, interval_sec=5.0, symbol="BTC/USD"
        )
        signal = feed_ticks(runner, ticks)
        self.assertIsNone(signal)

        suppressed = metric.get_counter_value(metric.signals_suppressed_total, reason="MinTradeStrengthRule") or 0.0
        self.assertEqual(suppressed, 0.0)

    def test_given_btc_kill_resume_then_eth_buffer_is_cleared(self) -> None:
        """When a kill command is received for one symbol, the buffer for a different symbol should also be cleared to prevent contamination."""
        metric = NightwatchMetrics()
        strategy = MomentumBurstStrategy(threshold_pct=10, metric=metric)
        buffer = TickBuffer(max_ticks_per_symbol=30)
        risk_engine = RiskEngine(rules=[MinTradeStrengthRule(min_strength=1.0)])
        kill_switch = KillSwitch()
        runner = StrategyRunner(strategy=strategy, buffer=buffer, metric=metric, risk_engine=risk_engine, kill_switch=kill_switch)

        btc_ticks = make_tick_sequence(
            prices=[Decimal("100"), Decimal("105"), Decimal("115")], start=self.start_time, interval_sec=5.0, symbol="BTC/USD"
        )
        eth_ticks = make_tick_sequence(
            prices=[Decimal("10"), Decimal("10.5"), Decimal("11")], start=self.start_time, interval_sec=5.0, symbol="ETH/USD"
        )

        feed_ticks(runner, btc_ticks)
        feed_ticks(runner, eth_ticks)

        kill_switch.apply(BotControlEvent(kill=True, reason="test", timestamp=self.start_time))
        runner.on_market_tick(btc_ticks[-1])  # suppressed; sets _was_killed = True
        kill_switch.apply(BotControlEvent(kill=False, reason="test", timestamp=self.start_time))

        signal_eth = feed_ticks(runner, eth_ticks)
        self.assertIsNotNone(signal_eth)

    def test_given_btc_kill_resume_log_mentions_all_symbols(self) -> None:
        """When a kill command is received for one symbol, the log should mention all symbols whose buffers were cleared."""
        metric = NightwatchMetrics()
        strategy = MomentumBurstStrategy(threshold_pct=10, metric=metric)
        buffer = TickBuffer(max_ticks_per_symbol=30)
        risk_engine = RiskEngine(rules=[MinTradeStrengthRule(min_strength=1.0)])
        kill_switch = KillSwitch()
        runner = StrategyRunner(strategy=strategy, buffer=buffer, metric=metric, risk_engine=risk_engine, kill_switch=kill_switch)

        btc_ticks = make_tick_sequence(
            prices=[Decimal("100"), Decimal("105"), Decimal("115")], start=self.start_time, interval_sec=5.0, symbol="BTC/USD"
        )
        eth_ticks = make_tick_sequence(
            prices=[Decimal("10"), Decimal("10.5"), Decimal("11")], start=self.start_time, interval_sec=5.0, symbol="ETH/USD"
        )

        feed_ticks(runner, btc_ticks)
        feed_ticks(runner, eth_ticks)

        kill_switch.apply(BotControlEvent(kill=True, reason="test", timestamp=self.start_time))
        runner.on_market_tick(btc_ticks[-1])  # suppressed; sets _was_killed = True
        kill_switch.apply(BotControlEvent(kill=False, reason="test", timestamp=self.start_time))

        with self.assertLogs("Nightwatch.pipeline.strategy_runner", level="INFO") as log:
            runner.on_market_tick(eth_ticks[0])  # first tick after resume triggers buffer clear log

        log_output = "\n".join(log.output)
        self.assertIn("Buffers cleared for symbols: BTC/USD, ETH/USD", log_output)
