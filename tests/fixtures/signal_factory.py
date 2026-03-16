"""Factory functions to create test instances of the Signal model."""

from datetime import datetime, timezone
from typing import Any

from Nightwatch.models.signal import Signal


def make_signal(
    symbol: str = "BTC/USD",
    side: str = "BUY",
    strength: float = 0.8,
    strategy: str = "Mean Reversion",
    rationale: dict[str, float] = {"delta_pct": 0.05, "window_sec": 3.0, "threshold_pct": 0.02},
    source: str = "test",
    **kwargs: Any,
) -> Signal:
    """Helper function to create a Signal with default values for testing."""
    return Signal(
        timestamp=kwargs.pop("timestamp", datetime.now(timezone.utc)),
        symbol=symbol,
        side=side,
        strength=strength,
        strategy=strategy,
        rationale=rationale,
        source=source,
        schema_version=kwargs.pop("schema_version", 1),
        **kwargs,
    )
