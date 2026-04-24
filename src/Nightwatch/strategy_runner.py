"""Module responsible for running a trading strategy, including buffering market ticks."""

import json
import logging

from Nightwatch.kill_switch import KillSwitch
from Nightwatch.metrics import NightwatchMetrics
from Nightwatch.models.market_tick import MarketTick
from Nightwatch.models.signal import Signal
from Nightwatch.models.strategy_decision import StrategyDecision
from Nightwatch.models.tick_buffer import TickBuffer
from Nightwatch.risk_engine import RiskEngine
from Nightwatch.strategies.strategy import Strategy

LOGGER = logging.getLogger(__name__)


class StrategyRunner:
    """Manages the execution of a trading strategy, including buffering ticks."""

    def __init__(
        self,
        strategy: Strategy,
        buffer: TickBuffer,
        metric: NightwatchMetrics | None = None,
        risk_engine: RiskEngine | None = None,
        kill_switch: KillSwitch | None = None,
    ) -> None:
        """Initializes the StrategyRunner with the given strategy, tick buffer, and optional metrics."""
        self._strategy = strategy
        self._buffer = buffer
        self._metric = metric
        self._risk_engine = risk_engine if risk_engine is not None else RiskEngine.create_default(metrics=self._metric)
        self._kill_switch = kill_switch if kill_switch is not None else KillSwitch()
        self._was_killed: bool = False

    def on_market_tick(self, tick: MarketTick) -> Signal | None:
        """Process a market tick and determine if a trading signal should be emitted. Return None if Kill switch is active."""
        first_tick = self._buffer.get_first_tick(tick.symbol)
        self._buffer.add_tick(tick)
        if self._is_suppressed_by_kill_switch(tick):
            self._was_killed = True
            return None

        if self._was_killed:
            self._was_killed = False
            self._buffer.clear_all_ticks()
            self._buffer.add_tick(tick)
            first_tick = None
            LOGGER.info("Kill switch resumed — cleared buffer for all symbols (triggered by %s)", tick.symbol)

        if not first_tick:
            if self._metric:
                self._metric.signals_suppressed_total.labels(reason="first_tick").inc()
            LOGGER.info("Received first tick for symbol %s: %s", tick.symbol, tick.uid)
            return None

        strategy_decision = self._strategy.on_tick(symbol=tick.symbol, window=self._buffer.get_ticks(tick.symbol))
        if strategy_decision is None:
            return None
        signal = self._build_signal(tick, strategy_decision)
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
        return signal

    def _is_suppressed_by_kill_switch(self, tick: MarketTick) -> bool:
        """Check if the kill switch is active or not yet ready, and log suppression if so."""
        if not self._kill_switch.ready:
            if self._metric:
                self._metric.signals_suppressed_total.labels(reason="kill_switch_not_ready").inc()
            LOGGER.debug("Kill switch not ready — suppressing %s", tick.symbol)
            return True
        if not self._kill_switch.trading_enabled:
            if self._metric:
                self._metric.signals_suppressed_total.labels(reason="kill_switch").inc()
            LOGGER.debug("Kill switch active — suppressing %s", tick.symbol)
            return True
        return False

    def _build_signal(self, tick: MarketTick, decision: StrategyDecision) -> Signal:
        """Construct a Signal object from the given MarketTick and strategy decision."""
        return Signal(
            timestamp=tick.timestamp,
            symbol=tick.symbol,
            side=decision.side,
            strength=decision.strength,
            strategy=self._strategy.NAME,
            rationale=decision.rationale,
            source=tick.source,
            schema_version=tick.schema_version,
        )
