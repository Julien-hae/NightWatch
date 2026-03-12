# mypy: disable-error-code="import-untyped"
"""Test fixture for creating MarketTick instances for testing purposes."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from Nightwatch.models.market_tick import MarketTick


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
