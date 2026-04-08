"""Module responsible for running a trading strategy, including buffering market ticks and enforcing cooldown periods between signals."""

import json
import logging
from datetime import datetime, timedelta

from Nightwatch.metrics import NightwatchMetrics
from Nightwatch.models.market_tick import MarketTick
from Nightwatch.models.risk_engine import RiskEngine
from Nightwatch.models.signal import Signal
from Nightwatch.models.tick_buffer import TickBuffer
from Nightwatch.strategies.strategy import Strategy

LOGGER = logging.getLogger(__name__)


class StrategyRunner:
    """Manages the execution of a trading strategy, including buffering ticks and enforcing cooldowns."""

    def __init__(
        self,
        strategy: Strategy,
        buffer: TickBuffer,
        cooldown: timedelta = timedelta(seconds=0),
        metric: NightwatchMetrics | None = None,
        risk_engine: RiskEngine | None = None,
    ) -> None:
        """Initializes the StrategyRunner with the given strategy, tick buffer, cooldown period, and optional metrics."""
        self._cooldown = cooldown
        self._strategy = strategy
        self._buffer = buffer
        self._metric = metric
        self._last_signal_time: dict[str, datetime] = {}
        self._risk_engine = risk_engine if risk_engine else RiskEngine()

    def on_market_tick(self, tick: MarketTick) -> Signal | None:
        """Process a market tick and determine if a trading signal should be emitted."""
        first_tick = self._buffer.get_first_tick(tick.symbol)
        self._buffer.add_tick(tick)
        if not first_tick:
            if self._metric:
                self._metric.signals_suppressed_total.labels(reason="first_tick").inc()
            LOGGER.info("Received first tick for symbol %s: %s", tick.symbol, tick.uid)
            return None
        last_signal = self._last_signal_time.get(tick.symbol, None)
        if last_signal is not None and tick.timestamp - last_signal < self._cooldown:
            if self._metric:
                self._metric.signals_suppressed_total.labels(reason="cooldown").inc()
            LOGGER.debug("Tick for symbol %s received during cooldown period: %s", tick.symbol, tick)
            return None

        strategy_decision = self._strategy.on_tick(symbol=tick.symbol, window=self._buffer.get_ticks(tick.symbol))
        signal = None
        if strategy_decision:
            signal = Signal(
                timestamp=tick.timestamp,
                symbol=tick.symbol,
                side=strategy_decision.side,
                strength=strategy_decision.strength,
                strategy=self._strategy.NAME,
                rationale=strategy_decision.rationale,
                source=tick.source,
                schema_version=tick.schema_version,
            )
            if signal:
                if self._metric:
                    self._metric.signals_total.labels(symbol=tick.symbol, side=signal.side.value, strategy=signal.strategy).inc()
                risk_decision = self._risk_engine.evaluate(signal)
                if not risk_decision.allowed:
                    if self._metric:
                        self._metric.signals_suppressed_total.labels(reason=risk_decision.rule).inc()
                    LOGGER.info(
                        "Signal %s for symbol %s rejected by rule %s: %s",
                        signal.uid,
                        signal.symbol,
                        risk_decision.rule,
                        risk_decision.reason,
                    )
                    return None
            log = {
                "event": "signal",
                "signal_id": str(signal.uid),
                "symbol": tick.symbol,
                "side": signal.side.value,
                "strategy": signal.strategy,
                "delta_pct": signal.rationale.get("delta_pct", None),
                "window_sec": signal.rationale.get("window_sec", None),
                "threshold_pct": signal.rationale.get("threshold_pct", None),
            }
            LOGGER.info(json.dumps(log, default=str))
            self._last_signal_time[tick.symbol] = tick.timestamp
        return signal
