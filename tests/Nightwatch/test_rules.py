# mypy: disable-error-code="union-attr"
"""Unit tests for the rules in the Nightwatch application."""

import unittest

from Nightwatch.rules.cooldown_rule import CooldownRule
from Nightwatch.rules.max_trade_size_rule import MaxTradeSizeRule
from Nightwatch.rules.risk_rule import RiskRule
from tests.fixtures.signal_factory import make_signal


class TestRules(unittest.TestCase):
    """Unit tests for the rules in the Nightwatch application."""

    def setUp(self) -> None:
        """Set up common test data."""
        self.signal = make_signal()
        self.cooldown_rule = CooldownRule(cooldown_seconds=1.0)
        self.max_trade_size_rule = MaxTradeSizeRule(max_strength=5.0)

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

    def test_max_trade_size_rule_blocks_large_signal(self) -> None:
        """Test that MaxTradeSizeRule blocks a signal with strength above the maximum."""
        large_signal = make_signal(strength=10.0)
        decision = self.max_trade_size_rule.evaluate(large_signal)
        self.assertIsNotNone(decision)  # Signal should be blocked
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "Trade size exceeds maximum")
        self.assertEqual(decision.rule, "MaxTradeSizeRule")
