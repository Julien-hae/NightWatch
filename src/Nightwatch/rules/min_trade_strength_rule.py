"""Max trade size risk rule — rejects signals whose strength exceeds a configured maximum."""

from Nightwatch.models.risk_decision import RiskDecision
from Nightwatch.models.signal import Signal
from Nightwatch.rules.risk_rule import RiskRule


class MinTradeStrengthRule(RiskRule):
    """Reject signals where strength is below a configured minimum."""

    def __init__(self, min_strength: float = 10.0) -> None:
        """Initialize with the minimum allowed signal strength."""
        self._min_strength = min_strength

    @property
    def name(self) -> str:
        """Return the rule name."""
        return "MinTradeStrengthRule"

    def evaluate(self, signal: Signal) -> RiskDecision | None:
        """Reject if signal.strength is below min_strength."""
        if signal.strength < self._min_strength:
            return RiskDecision(
                allowed=False,
                symbol=signal.symbol,
                signal_id=signal.uid,
                reason="Trade strength below minimum",
                rule=self.name,
            )
        return None
