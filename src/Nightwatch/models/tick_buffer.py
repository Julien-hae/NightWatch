"""Defines the TickBuffer Pydantic model for storing the last N MarketTick objects per symbol in a rolling buffer."""

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from pydantic import ConfigDict, Field
from pydantic.dataclasses import dataclass

from Nightwatch.models.market_tick import MarketTick


@dataclass(config=ConfigDict(str_max_length=255))
class TickBuffer:
    """Model to represent a buffer for storing recent MarketTick data."""

    max_ticks_per_symbol: int = Field(default=30, ge=1)
    ticks: dict[str, deque[MarketTick]] = Field(default_factory=dict)

    def __post_init__(self) -> None:
        """Initialize the ticks dictionary with a default factory to create deques for each symbol."""
        if not self.ticks:
            self.ticks = defaultdict(lambda: deque(maxlen=self.max_ticks_per_symbol))
        elif not isinstance(self.ticks, defaultdict):
            self.ticks = defaultdict(lambda: deque(maxlen=self.max_ticks_per_symbol), self.ticks)

    def add_tick(self, tick: MarketTick) -> None:
        """Add a tick to the per-symbol buffer, maintaining a rolling window up to max_ticks_per_symbol."""
        self.ticks[tick.symbol].append(tick)

    def get_ticks(self, symbol: str) -> deque[MarketTick]:
        """Return the internal deque of ticks for *symbol*, or an empty deque if none are stored.

        The returned deque is the live internal buffer — callers must not append or remove elements.
        """
        return self.ticks.get(symbol, deque())

    def get_latest_tick(self, symbol: str) -> MarketTick | None:
        """Return the most recent tick for *symbol*, or None if no ticks are available."""
        ticks = self.ticks.get(symbol, None)
        return ticks[-1] if ticks else None

    def get_first_tick(self, symbol: str) -> MarketTick | None:
        """Return the oldest tick for *symbol*, or None if no ticks are available."""
        ticks = self.ticks.get(symbol, None)
        return ticks[0] if ticks else None

    def get_ticks_within(self, symbol: str, seconds: float) -> deque[MarketTick]:
        """Return ticks for *symbol* that fall within the last *seconds* seconds."""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=seconds)
        return deque(t for t in self.ticks.get(symbol, []) if t.timestamp >= cutoff)
