"""Risk Engine module for Nightwatch."""

from Nightwatch.models.risk_decision import RiskDecision
from Nightwatch.models.signal import Signal
from Nightwatch.rules.cooldown_rule import CooldownRule
from Nightwatch.rules.max_trade_size_rule import MaxTradeSizeRule
from Nightwatch.rules.risk_rule import RiskRule


class RiskEngine:
    """Evaluates trading signals against an ordered list of risk rules.

    Rules are evaluated in order. The first rule that rejects the signal
    determines the RiskDecision. If all rules pass, the signal is allowed.
    """

    def __init__(self, rules: list[RiskRule] | None = None) -> None:
        """Initialize with an ordered list of risk rules.

        Args:
            rules: Rules to evaluate, in order. Defaults to
                   [CooldownRule(), MaxTradeSizeRule()] if not provided.
        """
        self._rules = rules if rules is not None else [CooldownRule(), MaxTradeSizeRule()]

    def evaluate(self, signal: Signal) -> RiskDecision:
        """Evaluate a trading signal against all rules, short-circuiting on first rejection."""
        for rule in self._rules:
            decision = rule.evaluate(signal)
            if decision is not None:
                return decision

        return RiskDecision(
            allowed=True,
            symbol=signal.symbol,
            signal_id=signal.uid,
        )
