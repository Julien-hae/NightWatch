"""A trading strategy that generates BUY or SELL signals when price moves beyond a configured percentage threshold."""

import logging
from collections import deque
from datetime import timedelta
from decimal import Decimal

from Nightwatch.metrics import NightwatchMetrics
from Nightwatch.models.market_tick import MarketTick
from Nightwatch.models.signal import Side
from Nightwatch.models.strategy_decision import StrategyDecision
from Nightwatch.strategies.strategy import Strategy

LOGGER = logging.getLogger(__name__)


class MomentumBurstStrategy(Strategy):
    """A trading strategy that generates BUY or SELL signals when price moves beyond a configured percentage threshold."""

    NAME: str = "momentum_burst_v1"

    def __init__(self, window_sec: float = 10.0, threshold_pct: float = 0.30, metric: NightwatchMetrics | None = None) -> None:
        """Initializes the MomentumBurstStrategy with the specified window size and threshold percentage."""
        if window_sec <= 0:
            raise ValueError("window_sec must be greater than 0")
        if threshold_pct <= 0:
            raise ValueError("threshold_pct must be greater than 0")
        self.window_sec = window_sec
        self.threshold_pct = Decimal(str(threshold_pct))
        self._metric = metric

    def on_tick(self, symbol: str, window: deque[MarketTick]) -> StrategyDecision | None:
        """Generates a BUY or SELL StrategyDecision if the price has been rising or falling and crosses a certain threshold.

        Args:
            symbol (str): The symbol for which the market tick is received.
            window (deque[MarketTick]): A deque containing the recent market ticks.

        Returns:
            StrategyDecision | None: A StrategyDecision if the conditions are met, otherwise None.
        """
        if self._metric:
            self._metric.strategy_evaluations_total.labels(symbol=symbol, strategy=self.NAME).inc()

        if len(window) < 2:  # noqa: PLR2004
            LOGGER.debug(
                "Not enough ticks in the window to evaluate the strategy for symbol %s. Required: 2, Found: %d", symbol, len(window)
            )
            return None

        last_tick: MarketTick = window[-1]
        cutoff_timestamp = last_tick.timestamp - timedelta(seconds=self.window_sec)
        window_in_range = [tick for tick in window if tick.timestamp >= cutoff_timestamp]
        if len(window_in_range) < 2:  # noqa: PLR2004
            LOGGER.debug(
                "Not enough ticks within the last %s seconds to evaluate the strategy for symbol %s. Required: 2, Found: %d",
                self.window_sec,
                symbol,
                len(window_in_range),
            )
            return None
        start_tick: MarketTick = window_in_range[0]

        if start_tick.price == Decimal("0"):
            LOGGER.warning("Start tick price is zero for symbol %s, cannot calculate percentage change.", symbol)
            return None
        if last_tick.timestamp <= start_tick.timestamp:
            LOGGER.warning(
                "Last tick timestamp %s is not greater than start tick timestamp %s for symbol %s, cannot calculate percentage change.",
                last_tick.timestamp,
                start_tick.timestamp,
                symbol,
            )
            return None
        delta_pct = (last_tick.price - start_tick.price) / start_tick.price * 100

        if delta_pct >= self.threshold_pct:
            side = Side.BUY
        elif delta_pct <= -self.threshold_pct:
            side = Side.SELL
        else:
            LOGGER.debug("Delta percentage %s for symbol %s did not cross any threshold.", delta_pct, symbol)
            return None

        return StrategyDecision(
            side=side,
            strength=float(abs(delta_pct)),
            rationale={
                "delta_pct": float(delta_pct),
                "window_sec": self.window_sec,
                "threshold_pct": self.threshold_pct,
            },
        )
