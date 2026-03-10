"""Define the TickBuffer model  data ticks."""

from typing import List

from pydantic import BaseModel, ConfigDict, Field

from Nightwatch.models.market_tick import MarketTick


class TickBuffer(BaseModel):
    """Model to represent a buffer."""

    ticks: dict[str, List[MarketTick]] = Field(default_factory=dict)
    max_ticks_per_symbol: int = 30

    model_config = ConfigDict(str_max_length=255)

    def add_tick(self, tick: MarketTick) -> None:
        """Add a tick to the buffer, replacing any existing tick for the same symbol."""
        if tick.symbol not in self.ticks:
            self.ticks[tick.symbol] = []
        self.ticks[tick.symbol].append(tick)
        while len(self.ticks[tick.symbol]) > self.max_ticks_per_symbol:
            self.ticks[tick.symbol].pop(0)
