"""Risk Engine module for Nightwatch."""

from Nightwatch.metrics.metrics import NightwatchMetrics
from Nightwatch.models.risk_decision import RiskDecision
from Nightwatch.models.signal import Signal
from Nightwatch.rules.cooldown_rule import CooldownRule
from Nightwatch.rules.max_signal_per_minute_rule import MaxSignalPerMinuteRule
from Nightwatch.rules.min_trade_strength_rule import MinTradeStrengthRule
from Nightwatch.rules.risk_rule import RiskRule


class RiskEngine:
    """Evaluates trading signals against an ordered list of risk rules.

    Rules are evaluated in order. The first rule that rejects the signal
    determines the RiskDecision. If all rules pass, the signal is allowed.

    Use `RiskEngine.create_default()` to obtain an instance with the standard
    production rule set and explicit thresholds.
    """

    def __init__(self, rules: list[RiskRule], metrics: NightwatchMetrics | None = None) -> None:
        """Initialize with an ordered list of risk rules.

        Args:
            rules: Rules to evaluate, in order. Must not be None; use
                   `RiskEngine.create_default()` to get the standard production configuration.
            metrics: Optional NightwatchMetrics instance for recording metrics. If not provided, no metrics will be recorded.
        """
        if not rules:
            raise ValueError("RiskEngine must be initialized with at least one rule.")
        self._rules = rules
        self._metrics = metrics

    @classmethod
    def create_default(cls, metrics: NightwatchMetrics | None = None) -> "RiskEngine":
        """Create a RiskEngine with the standard production rule set.

        All thresholds are stated explicitly here so that changes to rule-class
        defaults cannot silently alter production behaviour.

        Args:
            metrics: Optional NightwatchMetrics instance for recording metrics.

        Returns:
            A RiskEngine configured with CooldownRule, MinTradeStrengthRule,
            and MaxSignalPerMinuteRule using the production thresholds.
        """
        return cls(
            rules=[
                CooldownRule(cooldown_seconds=30.0),
                MinTradeStrengthRule(min_strength=10.0),
                MaxSignalPerMinuteRule(max_signals_per_min=5),
            ],
            metrics=metrics,
        )

    def evaluate(self, signal: Signal) -> RiskDecision:
        """Evaluate a trading signal against all rules, short-circuiting on first rejection."""
        if self._metrics is not None:
            self._metrics.risk_evaluations_total.labels(symbol=signal.symbol).inc()
        for rule in self._rules:
            decision = rule.evaluate(signal)
            if decision is not None:
                if self._metrics is not None:
                    reason = decision.reason or rule.name
                    self._metrics.signals_rejected_total.labels(symbol=signal.symbol, reason=reason).inc()
                return decision

        if self._metrics is not None:
            self._metrics.signals_allowed_total.labels(symbol=signal.symbol).inc()
        for rule in self._rules:
            rule.confirm(signal)

        return RiskDecision(
            allowed=True,
            symbol=signal.symbol,
            signal_id=signal.uid,
        )
