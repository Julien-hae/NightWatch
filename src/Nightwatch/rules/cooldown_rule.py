"""Cooldown risk rule — prevents signal spam for the same symbol+strategy."""

from datetime import datetime

from Nightwatch.models.risk_decision import RiskDecision
from Nightwatch.models.signal import Signal
from Nightwatch.rules.risk_rule import RiskRule


class CooldownRule(RiskRule):
    """Reject signals that arrive too soon after the last allowed signal for the same (symbol, strategy)."""

    def __init__(self, cooldown_seconds: float = 30.0) -> None:
        """Initialize with a non-negative cooldown period in seconds."""
        if cooldown_seconds < 0:
            msg = "cooldown_seconds must be greater than or equal to 0"
            raise ValueError(msg)
        self._cooldown_seconds = cooldown_seconds
        self._last_seen: dict[tuple[str, str], datetime] = {}

    @property
    def name(self) -> str:
        """Return the rule name."""
        return "CooldownRule"

    def evaluate(self, signal: Signal) -> RiskDecision | None:
        """Reject if a signal for the same (symbol, strategy) was allowed within cooldown_seconds."""
        key = (signal.symbol, signal.strategy)
        last = self._last_seen.get(key)

        if last is not None:
            elapsed = (signal.timestamp - last).total_seconds()
            if elapsed < self._cooldown_seconds:
                return RiskDecision(
                    allowed=False,
                    symbol=signal.symbol,
                    signal_id=signal.uid,
                    reason="Cooldown active",
                    rule=self.name,
                )
        return None

    def confirm(self, signal: Signal) -> None:
        """Update internal state to record that this signal has been allowed."""
        key = (signal.symbol, signal.strategy)
        self._last_seen[key] = signal.timestamp
        self._cleanup_last_seen_dict(signal.timestamp)

    def _cleanup_last_seen_dict(self, current_time: datetime) -> None:
        """Remove entries from _last_seen that are outside the cooldown window."""
        keys_to_delete = [key for key, last in self._last_seen.items() if (current_time - last).total_seconds() > self._cooldown_seconds]
        for key in keys_to_delete:
            del self._last_seen[key]
