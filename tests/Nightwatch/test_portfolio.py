"""Unit tests for the Portfolio model."""

import unittest
from decimal import Decimal

from Nightwatch.models.portfolio import Portfolio
from tests.fixtures.portfolio_factory import make_portfolio


class TestPortfolio(unittest.TestCase):
    """Unit tests for the Portfolio model."""

    def test_defaults_to_empty(self) -> None:
        """Test that a Portfolio can be created with default empty values."""
        portfolio = Portfolio()
        self.assertEqual(portfolio.positions, {})
        self.assertEqual(portfolio.last_prices, {})

    def test_position_qty_returns_zero_when_missing(self) -> None:
        """Test that position_qty returns 0 when no position is held for the symbol."""
        portfolio = make_portfolio()
        self.assertEqual(portfolio.position_qty("BTC/USD"), Decimal("0"))

    def test_position_qty_returns_held_quantity(self) -> None:
        """Test that position_qty returns the correct quantity for a held position."""
        portfolio = make_portfolio(positions={"BTC/USD": Decimal("0.5")})
        self.assertEqual(portfolio.position_qty("BTC/USD"), Decimal("0.5"))

    def test_last_price_returns_none_when_missing(self) -> None:
        """Test that last_price returns None when no price is known for the symbol."""
        portfolio = make_portfolio()
        self.assertIsNone(portfolio.last_price("BTC/USD"))

    def test_last_price_returns_known_price(self) -> None:
        """Test that last_price returns the correct price for a known symbol."""
        portfolio = make_portfolio(last_prices={"BTC/USD": Decimal("50000")})
        self.assertEqual(portfolio.last_price("BTC/USD"), Decimal("50000"))


if __name__ == "__main__":
    unittest.main()
