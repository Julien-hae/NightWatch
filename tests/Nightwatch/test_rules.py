# mypy: disable-error-code="union-attr"
"""Unit tests for the rules in the Nightwatch application."""

import unittest

from Nightwatch.rules.cooldown_rule import CooldownRule
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

    def test_cannot_instantiate_directly(self) -> None:
        """Given RiskRule is abstract, When instantiated, Then TypeError."""
        with self.assertRaises(TypeError):
            RiskRule()  # type: ignore

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
        decision1 = self.cooldown_rule.evaluate(self.signal)
        self.assertIsNone(decision1)  # First signal should be allowed

        # Simulate cooldown expiration by clearing the internal state
        self.cooldown_rule._last_seen.clear()

        decision2 = self.cooldown_rule.evaluate(self.signal)
        self.assertIsNone(decision2)  # Second signal should now be allowed
