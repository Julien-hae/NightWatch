"""Unit tests for the Risk Engine in the Nightwatch application."""

import unittest

from Nightwatch.metrics import NightwatchMetrics
from Nightwatch.models.risk_decision import RiskDecision
from Nightwatch.models.risk_engine import RiskEngine
from Nightwatch.models.signal import Signal
from Nightwatch.rules.cooldown_rule import CooldownRule
from Nightwatch.rules.min_trade_strength_rule import MinTradeStrengthRule
from Nightwatch.rules.risk_rule import RiskRule
from tests.fixtures.signal_factory import make_signal


class TestRiskEngine(unittest.TestCase):
    """Unit tests for the Risk Engine."""

    def setUp(self) -> None:
        """Set up common test data."""
        self.signal = make_signal(strength=99)
        self.metrics = NightwatchMetrics()
        self.risk_engine = RiskEngine(metrics=self.metrics)

    def test_evaluate_returns_risk_decision(self) -> None:
        """Test that the evaluate method returns a RiskDecision instance."""
        risk_decision = self.risk_engine.evaluate(self.signal)
        self.assertIsInstance(risk_decision, RiskDecision)

    def test_valid_signal_passes_all_rules(self) -> None:
        """Test that a valid signal that does not trigger any rules is allowed."""
        risk_decision = self.risk_engine.evaluate(self.signal)
        self.assertIsNone(risk_decision.reason)
        self.assertIsNone(risk_decision.rule)
        self.assertTrue(risk_decision.allowed)

    def test_rules_evaluated_in_order_cooldown_before_min_strength(self) -> None:
        """If cooldown and min-strength both apply, cooldown wins because it's first."""
        engine = RiskEngine(rules=[CooldownRule(), MinTradeStrengthRule(min_strength=0.5)])
        large_signal = make_signal(strength=1.0)

        _ = engine.evaluate(large_signal)

        risk_decision = engine.evaluate(large_signal)
        self.assertFalse(risk_decision.allowed)
        self.assertEqual(risk_decision.rule, "CooldownRule")

    def test_if_first_rule_rejects_no_further_rules_evaluated(self) -> None:
        """If the first rule rejects, subsequent rules are not called."""

        class SpyRule(RiskRule):
            """A rule that records whether it was called."""

            def __init__(self) -> None:
                self.called = False

            @property
            def name(self) -> str:
                """Return the rule name."""
                return "SpyRule"

            def evaluate(self, signal: Signal) -> RiskDecision | None:  # noqa: ARG002
                """Record that this rule was called, but do not reject."""
                self.called = True
                return None

        spy = SpyRule()
        engine = RiskEngine(rules=[CooldownRule(cooldown_seconds=9999), spy])

        engine.evaluate(self.signal)
        self.assertTrue(spy.called)

        spy.called = False
        engine.evaluate(self.signal)
        self.assertFalse(spy.called)

    def test_risk_evaluations_total_metric_increment(self) -> None:
        """Test that the total metric is incremented for each evaluation."""
        _ = self.risk_engine.evaluate(self.signal)
        self.assertEqual(self.metrics.get_counter_value(self.metrics.risk_evaluations_total, symbol=self.signal.symbol), 1)

    def test_signals_allowed_total_metric_increment(self) -> None:
        """Test that the signals allowed metric is incremented when a signal is allowed."""
        risk_decision = self.risk_engine.evaluate(self.signal)
        self.assertTrue(risk_decision.allowed)
        self.assertEqual(self.metrics.get_counter_value(self.metrics.signals_allowed_total, symbol=self.signal.symbol), 1)

    def test_signals_rejected_total_metric_increment(self) -> None:
        """Test that the signals suppressed metric is incremented when a signal is rejected."""
        risk_engine = RiskEngine(rules=[CooldownRule(cooldown_seconds=9999)], metrics=self.metrics)
        _ = risk_engine.evaluate(self.signal)
        risk_decision = risk_engine.evaluate(self.signal)
        self.assertFalse(risk_decision.allowed)
        self.assertEqual(
            self.metrics.get_counter_value(self.metrics.signals_rejected_total, symbol=self.signal.symbol, rule="CooldownRule"), 1
        )
