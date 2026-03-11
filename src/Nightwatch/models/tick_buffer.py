"""Defines the TickBuffer Pydantic model for storing the last N MarketTick objects per symbol in a rolling buffer."""

from collections import deque

from pydantic import BaseModel, ConfigDict, Field

from Nightwatch.models.market_tick import MarketTick


class TickBuffer(BaseModel):
    """Model to represent a buffer for storing recent MarketTick data."""

    ticks: dict[str, deque[MarketTick]] = Field(default_factory=dict)
    max_ticks_per_symbol: int = Field(default=30, ge=1)

    model_config = ConfigDict(str_max_length=255)

    def add_tick(self, tick: MarketTick) -> None:
        """Add a tick to the per-symbol buffer, maintaining a rolling window up to max_ticks_per_symbol."""
        if tick.symbol not in self.ticks:
            self.ticks[tick.symbol] = deque(maxlen=self.max_ticks_per_symbol)
        self.ticks[tick.symbol].append(tick)
