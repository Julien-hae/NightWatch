# mypy: disable-error-code="union-attr, import-untyped"
"""Unit tests for the rules in the Nightwatch application."""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from Nightwatch.rules.cooldown_rule import CooldownRule
from Nightwatch.rules.max_signal_per_minute_rule import MaxSignalPerMinuteRule
from Nightwatch.rules.min_trade_strenght_rule import MinTradeStrengthRule
from Nightwatch.rules.risk_rule import RiskRule
from tests.fixtures.signal_factory import make_signal


class TestRules(unittest.TestCase):
    """Unit tests for the rules in the Nightwatch application."""

    def setUp(self) -> None:
        """Set up common test data."""
        self.signal = make_signal()
        self.cooldown_rule = CooldownRule(cooldown_seconds=9999.0)
        self.min_trade_strength_rule = MinTradeStrengthRule(min_strength=80.0)
        self.max_signal_per_minute_rule = MaxSignalPerMinuteRule(max_signals_per_min=2)

    def test_cannot_instantiate_directly(self) -> None:
        """Given RiskRule is abstract, When instantiated, Then TypeError."""
        with self.assertRaises(TypeError):
            RiskRule()  # type: ignore[abstract]

    def test_cooldown_rule_blocks_signal_within_cooldown(self) -> None:
        """Test that CooldownRule blocks a second signal within the cooldown period."""
        decision1 = self.cooldown_rule.evaluate(self.signal)
        self.assertIsNone(decision1)  # First signal should be allowed

        decision2 = self.cooldown_rule.evaluate(self.signal)
        self.assertIsNotNone(decision2)  # Second signal should be blocked
        self.assertFalse(decision2.allowed)
        self.assertEqual(decision2.reason, "Cooldown active")
        self.assertEqual(decision2.rule, "CooldownRule")

    def test_min_trade_strength_rule_blocks_weak_signal(self) -> None:
        """Test that MinTradeStrengthRule blocks a signal with strength below the minimum."""
        weak_signal = make_signal(strength=1.0)
        decision = self.min_trade_strength_rule.evaluate(weak_signal)
        self.assertIsNotNone(decision)  # Signal should be blocked
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "Trade strength below minimum")
        self.assertEqual(decision.rule, "MinTradeStrengthRule")

    def test_cooldown_expired_allows_signal(self) -> None:
        """Test that CooldownRule allows a signal after the cooldown period has expired."""
        t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        cooldown_seconds = 1.0
        t1 = t0 + timedelta(seconds=cooldown_seconds)

        with patch("Nightwatch.rules.cooldown_rule.datetime") as mock_dt:
            mock_dt.now.side_effect = [t0, t0, t1]
            cooldown = CooldownRule(cooldown_seconds=cooldown_seconds)
            first_decision = cooldown.evaluate(self.signal)
            rejected_decision = cooldown.evaluate(self.signal)
            approved_decision = cooldown.evaluate(self.signal)

        self.assertIsNone(first_decision)
        self.assertIsNotNone(rejected_decision)
        self.assertIsNone(approved_decision)

    def test_max_signal_per_minute_rule_blocks_excess_signals(self) -> None:
        """Test that MaxSignalPerMinuteRule blocks signals after the maximum per minute is exceeded."""

        decision1 = self.max_signal_per_minute_rule.evaluate(self.signal)
        decision2 = self.max_signal_per_minute_rule.evaluate(self.signal)
        decision3 = self.max_signal_per_minute_rule.evaluate(self.signal)

        self.assertIsNone(decision1)
        self.assertIsNone(decision2)
        self.assertIsNotNone(decision3)
        self.assertFalse(decision3.allowed)
        self.assertEqual(decision3.reason, "Exceeded max signals per minute")
        self.assertEqual(decision3.rule, "MaxSignalPerMinuteRule")

    def test_max_signal_per_minute_rule_resets_after_one_minute(self) -> None:
        """Test that MaxSignalPerMinuteRule resets the count after one minute."""
        t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        t1 = t0 + timedelta(seconds=61)

        with patch("Nightwatch.rules.max_signal_per_minute_rule.datetime") as mock_dt:
            mock_dt.now.side_effect = [t0, t0, t1]
            rule = MaxSignalPerMinuteRule(max_signals_per_min=1)

            allowed_decision = rule.evaluate(self.signal)
            self.assertIsNone(allowed_decision)
            blocked_decision = rule.evaluate(self.signal)
            self.assertIsNotNone(blocked_decision)

            reset_decision = rule.evaluate(self.signal)
            self.assertIsNone(reset_decision)
