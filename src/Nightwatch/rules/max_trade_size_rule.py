"""Max trade size risk rule — rejects signals whose strength exceeds a configured maximum."""

from Nightwatch.models.risk_decision import RiskDecision
from Nightwatch.models.signal import Signal
from Nightwatch.rules.risk_rule import RiskRule


class MaxTradeSizeRule(RiskRule):
    """Reject signals where strength exceeds a configured maximum."""

    def __init__(self, max_strength: float = 10.0) -> None:
        """Initialize with the maximum allowed signal strength."""
        self._max_strength = max_strength

    @property
    def name(self) -> str:
        """Return the rule name."""
        return "MaxTradeSizeRule"

    def evaluate(self, signal: Signal) -> RiskDecision | None:
        """Reject if signal.strength exceeds max_strength."""
        if signal.strength > self._max_strength:
            return RiskDecision(
                allowed=False,
                symbol=signal.symbol,
                signal_id=signal.uid,
                reason="Trade size exceeds maximum",
                rule=self.name,
            )
        return None
