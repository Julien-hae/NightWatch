"""Module responsible for running a trading strategy, including buffering market ticks and enforcing cooldown periods between signals."""

import logging
from datetime import timedelta

from Nightwatch.metrics import NightwatchMetrics
from Nightwatch.models.market_tick import MarketTick
from Nightwatch.models.signal import Signal
from Nightwatch.models.tick_buffer import TickBuffer
from Nightwatch.strategies.strategy import Strategy

LOGGER = logging.getLogger(__name__)


class StrategyRunner:
    """Manages the execution of a trading strategy, including buffering ticks and enforcing cooldowns."""

    def __init__(
        self, strategy: Strategy, buffer: TickBuffer, cooldown: int | None = None, metric: NightwatchMetrics | None = None
    ) -> None:
        """Manages the execution of a trading strategy, including buffering ticks and enforcing cooldowns."""
        self._cooldown = cooldown
        self._strategy = strategy
        self._buffer = buffer
        self._metric = metric

    def on_market_tick(self, tick: MarketTick) -> Signal | None:
        """Process a market tick and determine if a trading signal should be emitted."""
        first_tick = self._buffer.get_first_tick(tick.symbol)
        self._buffer.add_tick(tick)
        if not first_tick:
            LOGGER.debug("Received first tick for symbol %s: %s", tick.symbol, tick)
            return None
        if tick.timestamp - first_tick.timestamp < timedelta(seconds=self._cooldown):  # type: ignore[arg-type]
            LOGGER.debug("Tick for symbol %s received during cooldown period: %s", tick.symbol, tick)
            return None

        signal = self._strategy.on_tick(symbol=tick.symbol, window=self._buffer.get_ticks(tick.symbol))
        if signal:
            LOGGER.debug("Emitting signal: %s for symbol: %s", signal, tick.symbol)
            if self._metric:
                self._metric.signals_total.labels(symbol=tick.symbol, side=signal.side).inc()
        return signal

    def get_signal_totals(self, **labels: str) -> float | None:
        """Return the total number of signals emitted by the strategy."""
        if self._metric:
            return self._metric.get_counter_value(self._metric.signals_total, **labels)
        return None
