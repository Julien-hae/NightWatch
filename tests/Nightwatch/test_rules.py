# mypy: disable-error-code="union-attr, import-untyped"
"""Unit tests for the rules in the Nightwatch application."""

import unittest
from datetime import timedelta

from Nightwatch.rules.cooldown_rule import CooldownRule
from Nightwatch.rules.max_signal_per_minute_rule import MaxSignalPerMinuteRule
from Nightwatch.rules.min_trade_strength_rule import MinTradeStrengthRule
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
        if decision1 is None:
            self.cooldown_rule.confirm(self.signal)

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
        cooldown = CooldownRule(cooldown_seconds=1.0)
        rejected_signal = make_signal(timestamp=self.signal.timestamp + timedelta(seconds=0.5))
        approved_signal = make_signal(timestamp=self.signal.timestamp + timedelta(seconds=1.5))

        first_decision = cooldown.evaluate(self.signal)
        if first_decision is None:
            cooldown.confirm(self.signal)
        rejected_decision = cooldown.evaluate(rejected_signal)
        approved_decision = cooldown.evaluate(approved_signal)

        self.assertIsNone(first_decision)
        self.assertIsNotNone(rejected_decision)
        self.assertIsNone(approved_decision)

    def test_max_signal_per_minute_rule_blocks_excess_signals(self) -> None:
        """Test that MaxSignalPerMinuteRule blocks signals after the maximum per minute is exceeded."""

        decision1 = self.max_signal_per_minute_rule.evaluate(self.signal)
        if decision1 is None:
            self.max_signal_per_minute_rule.confirm(self.signal)
        decision2 = self.max_signal_per_minute_rule.evaluate(self.signal)
        if decision2 is None:
            self.max_signal_per_minute_rule.confirm(self.signal)
        decision3 = self.max_signal_per_minute_rule.evaluate(self.signal)

        self.assertIsNone(decision1)
        self.assertIsNone(decision2)
        self.assertIsNotNone(decision3)
        self.assertFalse(decision3.allowed)
        self.assertEqual(decision3.reason, "Exceeded max signals per minute")
        self.assertEqual(decision3.rule, "MaxSignalPerMinuteRule")

    def test_max_signal_per_minute_rule_resets_after_one_minute(self) -> None:
        """Test that MaxSignalPerMinuteRule resets the count after one minute."""
        rule = MaxSignalPerMinuteRule(max_signals_per_min=1)

        allowed_decision = rule.evaluate(self.signal)
        self.assertIsNone(allowed_decision)
        if allowed_decision is None:
            rule.confirm(self.signal)
        blocked_signal = make_signal(timestamp=self.signal.timestamp + timedelta(seconds=30))
        blocked_decision = rule.evaluate(blocked_signal)
        self.assertIsNotNone(blocked_decision)

        reset_signal = make_signal(timestamp=self.signal.timestamp + timedelta(seconds=61))
        reset_decision = rule.evaluate(reset_signal)
        self.assertIsNone(reset_decision)

    def test_clean_up_max_signal_per_minute_rule(self) -> None:
        """Test that MaxSignalPerMinuteRule cleans up old entries from _last_seen."""
        rule = MaxSignalPerMinuteRule(max_signals_per_min=1)

        signal1 = make_signal(timestamp=self.signal.timestamp)
        signal2 = make_signal(timestamp=self.signal.timestamp + timedelta(seconds=30))
        signal3 = make_signal(timestamp=self.signal.timestamp + timedelta(seconds=61))

        decision1 = rule.evaluate(signal1)
        self.assertIsNone(decision1)
        if decision1 is None:
            rule.confirm(signal1)

        decision2 = rule.evaluate(signal2)
        self.assertIsNotNone(decision2)  # Should be blocked
        self.assertFalse(decision2.allowed)

        decision3 = rule.evaluate(signal3)
        self.assertIsNone(decision3)  # Should be allowed after cleanup
        self.assertEqual(len(rule._last_seen), 1)  # Only the entry for signal3 should remain

    def test_clean_up_cooldown_rule(self) -> None:
        """Test that CooldownRule cleans up old entries from _last_seen."""
        rule = CooldownRule(cooldown_seconds=1.0)

        signal1 = make_signal(timestamp=self.signal.timestamp)
        signal2 = make_signal(timestamp=self.signal.timestamp + timedelta(seconds=0.5))
        signal3 = make_signal(timestamp=self.signal.timestamp + timedelta(seconds=1.5))

        decision1 = rule.evaluate(signal1)
        self.assertIsNone(decision1)
        if decision1 is None:
            rule.confirm(signal1)

        decision2 = rule.evaluate(signal2)
        self.assertIsNotNone(decision2)  # Should be blocked
        self.assertFalse(decision2.allowed)

        decision3 = rule.evaluate(signal3)
        self.assertIsNone(decision3)  # Should be allowed after cleanup
        self.assertEqual(len(rule._last_seen), 1)  # Only the entry for signal3 should remain
