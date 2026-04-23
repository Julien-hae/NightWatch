# mypy: disable-error-code="import-untyped"
"""Tests for the Strategy class."""

from collections import deque

from Nightwatch.models.market_tick import MarketTick
from Nightwatch.models.signal import Side
from Nightwatch.models.strategy_decision import StrategyDecision
from Nightwatch.strategies.strategy import Strategy


class NoneStrategy(Strategy):  # type: ignore[misc]
    """A concrete implementation of the Strategy class for testing purposes."""

    NAME = "none_strategy"

    def __init__(self) -> None:
        """Initialize the Strategy class."""
        super().__init__()

    def on_tick(self, symbol: str, window: deque[MarketTick]) -> StrategyDecision | None:  # noqa: ARG002
        """A simple implementation of the on_tick method that always returns None."""
        return None


class AlwaysSignalStrategy(Strategy):  # type: ignore[misc]
    """A concrete implementation of the Strategy class that always emits a BUY signal."""

    NAME = "always_signal_strategy"

    def __init__(self) -> None:
        """Initialize the Strategy class."""
        super().__init__()

    def on_tick(self, symbol: str, window: deque[MarketTick]) -> StrategyDecision | None:  # noqa: ARG002
        """Always returns a BUY StrategyDecision."""

        return StrategyDecision(side=Side.BUY, strength=100.0, rationale={})
