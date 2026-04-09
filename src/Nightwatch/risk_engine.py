"""Risk Engine module for Nightwatch."""

from Nightwatch.metrics import NightwatchMetrics
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
    """

    def __init__(self, rules: list[RiskRule] | None = None, metrics: NightwatchMetrics | None = None) -> None:
        """Initialize with an ordered list of risk rules.

        Args:
            rules: Rules to evaluate, in order. Defaults to
                   [CooldownRule(), MinTradeStrengthRule(), MaxSignalPerMinuteRule()] if not provided.
            metrics: Optional NightwatchMetrics instance for recording metrics. If not provided, no metrics will be recorded.
        """
        self._rules = rules if rules is not None else [CooldownRule(), MinTradeStrengthRule(), MaxSignalPerMinuteRule()]
        self._metrics = metrics

    def evaluate(self, signal: Signal) -> RiskDecision:
        """Evaluate a trading signal against all rules, short-circuiting on first rejection."""
        if self._metrics is not None:
            self._metrics.risk_evaluations_total.labels(symbol=signal.symbol).inc()
        for rule in self._rules:
            decision = rule.evaluate(signal)
            if decision is not None:
                if self._metrics is not None:
                    self._metrics.signals_rejected_total.labels(symbol=signal.symbol, rule=rule.name).inc()
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
