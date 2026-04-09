"""Rate-limit signals per minute for the same symbol and strategy."""

from collections import deque
from datetime import datetime, timezone

from Nightwatch.models.risk_decision import RiskDecision
from Nightwatch.models.signal import Signal
from Nightwatch.rules.risk_rule import RiskRule


class MaxSignalPerMinuteRule(RiskRule):
    """Reject signals that exceed a maximum number of allowed signals per minute for the same (symbol, strategy)."""

    def __init__(self, max_signals_per_min: int = 5) -> None:
        """Initialize with a non-negative maximum number of signals per minute."""
        if max_signals_per_min < 0:
            msg = "max_signals_per_min must be greater than or equal to 0"
            raise ValueError(msg)
        self._max_signals_per_min = max_signals_per_min
        self._last_seen: dict[tuple[str, str], deque[datetime]] = {}

    @property
    def name(self) -> str:
        """Return the rule name."""
        return "MaxSignalPerMinuteRule"

    def evaluate(self, signal: Signal) -> RiskDecision | None:
        """Reject if a signal for the same (symbol, strategy) exceeds the maximum allowed per minute."""
        key = (signal.symbol, signal.strategy)
        last = self._last_seen.get(key)

        if last is not None and len(last) >= self._max_signals_per_min:
            now = datetime.now(timezone.utc)
            while last and (now - last[0]).total_seconds() > 60:  # noqa: PLR2004
                last.popleft()

            if len(last) >= self._max_signals_per_min:
                return RiskDecision(
                    allowed=False,
                    symbol=signal.symbol,
                    signal_id=signal.uid,
                    reason="Exceeded max signals per minute",
                    rule=self.name,
                )

        return None

    def confirm(self, signal: Signal) -> None:
        """Update internal state to record that this signal has been allowed."""
        key = (signal.symbol, signal.strategy)
        now = datetime.now(timezone.utc)
        last = self._last_seen.get(key)
        if last is None:
            last = deque(maxlen=self._max_signals_per_min)
        last.append(now)
        self._last_seen[key] = last
