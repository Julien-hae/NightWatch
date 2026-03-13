"""Defines the TickBuffer Pydantic model for storing the last N MarketTick objects per symbol in a rolling buffer."""

from collections import defaultdict, deque

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
        """Get the deque of ticks for a given symbol, or an empty deque if no ticks are stored for that symbol."""
        return deque(self.ticks.get(symbol, []))
