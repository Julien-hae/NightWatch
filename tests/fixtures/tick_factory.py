# mypy: disable-error-code="import-untyped"
"""Test fixture for creating MarketTick instances for testing purposes."""

from collections import deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from Nightwatch.models.market_tick import MarketTick
from Nightwatch.models.signal import Signal
from Nightwatch.pipeline.strategy_runner import StrategyRunner


def make_tick(
    symbol: str = "BTC/USD",
    price: Decimal = Decimal("50000.0"),
    source: str = "test",
    **kwargs: Any,
) -> MarketTick:
    """Helper function to create a MarketTick with default values for testing."""
    return MarketTick(
        timestamp=kwargs.pop("timestamp", datetime.now(timezone.utc)),
        symbol=symbol,
        price=price,
        source=source,
        schema_version=kwargs.pop("schema_version", 1),
        **kwargs,
    )


def feed_ticks(runner: StrategyRunner, ticks: deque[MarketTick]) -> Signal | None:
    """Feed ticks into the runner, returning the first signal (or None)."""
    for tick in ticks:
        signal = runner.on_market_tick(tick)
        if signal is not None:
            return signal
    return None


def make_tick_sequence(
    prices: list[Decimal],
    start: datetime,
    interval_sec: float = 5.0,
    symbol: str = "BTC/USD",
) -> deque[MarketTick]:
    """Build a deque of ticks with evenly spaced timestamps."""
    return deque(make_tick(price=p, timestamp=start + timedelta(seconds=i * interval_sec), symbol=symbol) for i, p in enumerate(prices))
