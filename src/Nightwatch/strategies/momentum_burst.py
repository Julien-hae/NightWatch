"""A trading strategy that generates buy signals when a rising sequence of ticks crosses a certain threshold."""

import logging
from collections import deque
from decimal import Decimal

from Nightwatch.models.market_tick import MarketTick
from Nightwatch.models.signal import Signal
from Nightwatch.strategies.strategy import Strategy

LOGGER = logging.getLogger(__name__)


class MomentumBurstStrategy(Strategy):
    """A trading strategy that generates buy signals when a rising sequence of ticks crosses a certain threshold."""

    def __init__(self, window_sec: float = 10.0, threshold_pct: float = 30) -> None:
        """Initializes the MomentumBurstStrategy with the specified window size and threshold percentage."""
        self.window_sec = window_sec
        self.threshold_pct = threshold_pct

    def on_tick(self, symbol: str, window: deque[MarketTick]) -> Signal | None:
        """Generates a buy signal if the price has been rising and crosses a certain threshold.

        Args:
            symbol (str): The symbol for which the market tick is received.
            window (deque[MarketTick]): A deque containing the recent market ticks.

        Returns:
            Signal | None: A buy signal if the conditions are met, otherwise None.
        """
        if len(window) < 2:  # noqa: PLR2004
            LOGGER.debug(
                "Not enough ticks in the window to evaluate the strategy for symbol %s. Required: 2, Found: %d", symbol, len(window)
            )
            return None

        start_tick: MarketTick = window[0]
        last_tick: MarketTick = window[-1]

        if start_tick.price == Decimal("0"):
            LOGGER.warning("Start tick price is zero for symbol %s, cannot calculate percentage change.", symbol)
            return None

        delta_pct = (last_tick.price - start_tick.price) / start_tick.price * 100
        if delta_pct >= Decimal(str(self.threshold_pct)):
            side = "BUY"
        elif delta_pct <= Decimal(str(-self.threshold_pct)):
            side = "SELL"
        else:
            LOGGER.debug("Delta percentage %s for symbol %s did not cross any threshold.", delta_pct, symbol)
            return None

        return Signal(
            timestamp=last_tick.timestamp,
            symbol=symbol,
            side=side,
            strength=float(abs(delta_pct)),
            strategy="momentum_burst_v1",
            rationale={
                "delta_pct": float(delta_pct),
                "window_sec": self.window_sec,
                "threshold_pct": self.threshold_pct,
            },
            source="trade-service",
            schema_version=1,
        )
