"""Unit tests for the RiskDecision model in the Nightwatch application."""

import unittest

from tests.fixtures.risk_decision_factory import make_risk_decision


class TestRiskDecision(unittest.TestCase):
    """Unit tests for the RiskDecision model."""

    def test_true_decision_implies_fields_are_none(self) -> None:
        """Test that when allowed is True, reason and rule are None."""
        risk_decision = make_risk_decision(allowed=True, reason=None, rule=None)
        self.assertTrue(risk_decision.allowed)
        self.assertIsNone(risk_decision.reason)
        self.assertIsNone(risk_decision.rule)

    def test_non_blank_symbol(self) -> None:
        """Test that the symbol field cannot be blank or just whitespace."""
        with self.assertRaises(ValueError):
            make_risk_decision(symbol="   ")

    def test_false_decision_requires_reason_and_rule(self) -> None:
        """Test that when allowed is False, reason and rule are provided."""
        risk_decision = make_risk_decision(allowed=False, reason="Risk too high", rule="Max drawdown exceeded")
        self.assertFalse(risk_decision.allowed)
        self.assertIsNotNone(risk_decision.reason)
        self.assertIsNotNone(risk_decision.rule)

    def test_reason_and_rule_required_when_allowed_is_false(self) -> None:
        """Test that when allowed is False, reason and rule cannot be None."""
        with self.assertRaises(ValueError):
            make_risk_decision(allowed=False, reason=None, rule="Some rule")
        with self.assertRaises(ValueError):
            make_risk_decision(allowed=False, reason="Some reason", rule=None)

    def test_reason_and_rule_must_be_none_when_allowed_is_true(self) -> None:
        """Test that when allowed is True, reason and rule must be None."""
        with self.assertRaises(ValueError):
            make_risk_decision(allowed=True, reason="Some reason", rule=None)
        with self.assertRaises(ValueError):
            make_risk_decision(allowed=True, reason=None, rule="Some rule")
