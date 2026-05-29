"""Factory functions to create test instances of the Portfolio model."""

from decimal import Decimal
from typing import Any

from Nightwatch.models.portfolio import Portfolio  # type: ignore[import-untyped]


def make_portfolio(
    cash: Decimal = Decimal("0"),
    positions: dict[str, Decimal] | None = None,
    last_prices: dict[str, Decimal] | None = None,
    **kwargs: Any,
) -> Portfolio:
    """Helper function to create a Portfolio with default values for testing."""
    return Portfolio(
        cash=cash,
        positions={} if positions is None else positions,
        last_prices={} if last_prices is None else last_prices,
        **kwargs,
    )
