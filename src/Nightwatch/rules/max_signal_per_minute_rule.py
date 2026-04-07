"""Cooldown risk rule — prevents signal spam for the same symbol+strategy."""

from collections import deque
from datetime import datetime, timezone
from typing import Tuple

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
        self._last_seen: dict[tuple[str, str], deque[Tuple[Signal, datetime]]] = {}

    @property
    def name(self) -> str:
        """Return the rule name."""
        return "MaxSignalPerMinuteRule"

    def evaluate(self, signal: Signal) -> RiskDecision | None:
        """Reject if a signal for the same (symbol, strategy) exceeds the maximum allowed per minute."""
        key = (signal.symbol, signal.strategy)
        now = datetime.now(timezone.utc)
        last = self._last_seen.get(key)

        if last is not None:
            while last and (now - last[0][1]).total_seconds() > 60:  # noqa: PLR2004
                last.popleft()

            if len(last) >= self._max_signals_per_min:
                return RiskDecision(
                    allowed=False,
                    symbol=signal.symbol,
                    signal_id=signal.uid,
                    reason="Exceeded max signals per minute",
                    rule=self.name,
                )

        if last is None:
            last = deque()
            self._last_seen[key] = last

        last.append((signal, now))
        return None
