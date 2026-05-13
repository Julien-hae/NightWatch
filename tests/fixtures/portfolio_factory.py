"""Factory functions to create test instances of the Portfolio model."""

from decimal import Decimal
from typing import Any

from Nightwatch.models.portfolio import Portfolio


def make_portfolio(
    positions: dict[str, Decimal] | None = None,
    last_prices: dict[str, Decimal] | None = None,
    **kwargs: Any,
) -> Portfolio:
    """Helper function to create a Portfolio with default values for testing."""
    return Portfolio(
        positions=positions or {},
        last_prices=last_prices or {},
        **kwargs,
    )
