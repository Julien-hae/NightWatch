"""Rate-limit signals per minute for the same symbol and strategy."""

from collections import deque
from datetime import datetime

from sortedcontainers import SortedDict  # type: ignore[import-untyped]

from Nightwatch.models.risk_decision import RiskDecision
from Nightwatch.models.signal import Signal
from Nightwatch.rules.risk_rule import RiskRule


class MaxSignalPerMinuteRule(RiskRule):
    """Reject signals that exceed a maximum number of allowed signals per minute for the same (symbol, strategy)."""

    def __init__(self, max_signals_per_min: int = 5) -> None:
        """Initialize with a non-negative maximum number of signals per minute."""
        if max_signals_per_min <= 0:
            msg = "max_signals_per_min must be greater than 0"
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
        last = self._last_seen.get(key, deque(maxlen=self._max_signals_per_min))

        while last and (signal.timestamp - last[0]).total_seconds() > 60:  # noqa: PLR2004
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
        last = self._last_seen.get(key)
        if last is None:
            last = deque(maxlen=self._max_signals_per_min)
        last.append(signal.timestamp)
        self._last_seen[key] = last
        self._cleanup_last_seen_dict(signal.timestamp)

    def _cleanup_last_seen_dict(self, current_time: datetime) -> None:
        """Remove entries from _last_seen that are outside the 1-minute window."""
        self._last_seen = SortedDict(
            (key, timestamps)
            for key, timestamps in self._last_seen.items()
            if timestamps and (current_time - timestamps[-1]).total_seconds() <= 60  # noqa: PLR2004
        )
