"""Defines the TickBuffer Pydantic model for storing the last N MarketTick objects per symbol in a rolling buffer."""

import bisect
import logging
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from pydantic import ConfigDict, Field
from pydantic.dataclasses import dataclass

from Nightwatch.models.market_tick import MarketTick

LOGGER = logging.getLogger(__name__)


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
        """Add a tick to the per-symbol buffer, maintaining a rolling window up to max_ticks_per_symbol.

        Ticks must arrive in non-decreasing timestamp order. Out-of-order ticks (where the new
        tick's timestamp is strictly earlier than the latest stored tick) are discarded with a
        warning, preserving the sorted-by-timestamp invariant required for bisect-based lookups.
        """
        symbol_ticks = self.ticks[tick.symbol]
        if symbol_ticks and tick.timestamp < symbol_ticks[-1].timestamp:
            LOGGER.warning(
                "Discarding out-of-order tick for %s: tick timestamp %s is before latest %s",
                tick.symbol,
                tick.timestamp,
                symbol_ticks[-1].timestamp,
            )
            return
        symbol_ticks.append(tick)

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
        ticks: deque[MarketTick] = self.ticks.get(symbol, deque())
        tick_list = list(ticks)
        timestamps = [tick.timestamp for tick in tick_list]
        index = bisect.bisect_left(timestamps, cutoff)
        return deque(tick_list[index:])

    def clear_ticks(self, symbol: str) -> None:
        """Clear all ticks for *symbol*."""
        self.ticks[symbol].clear()

    def clear_all_ticks(self) -> None:
        """Clear all ticks for all symbols."""
        for symbol in self.ticks:
            self.ticks[symbol].clear()
