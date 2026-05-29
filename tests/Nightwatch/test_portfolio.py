"""Unit tests for the Portfolio model."""

import unittest
from decimal import Decimal

from Nightwatch.models.portfolio import Portfolio  # type: ignore[import-untyped]
from Nightwatch.models.signal import Side  # type: ignore[import-untyped]
from tests.fixtures.fill_factory import make_fill
from tests.fixtures.portfolio_factory import make_portfolio


class TestPortfolio(unittest.TestCase):
    """Unit tests for the Portfolio model."""

    def test_defaults_to_empty(self) -> None:
        """Test that a Portfolio can be created with default empty values."""
        portfolio = Portfolio()
        self.assertEqual(portfolio.cash, Decimal("0"))
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


class TestPortfolioApplyFill(unittest.TestCase):
    """Unit tests for Portfolio.apply_fill and equity computation."""

    def test_buy_updates_cash_and_position(self) -> None:
        portfolio = make_portfolio(cash=Decimal("2000"))
        fill = make_fill(
            symbol="BTC/USD",
            side=Side.BUY,
            qty=Decimal("0.002"),
            price=Decimal("50000"),
            fee=Decimal("0.10"),
        )
        portfolio.apply_fill(fill)
        self.assertEqual(portfolio.cash, Decimal("1899.90"))
        self.assertEqual(portfolio.position_qty("BTC/USD"), Decimal("0.002"))
        self.assertEqual(portfolio.last_price("BTC/USD"), Decimal("50000"))

    def test_sell_updates_cash_and_position(self) -> None:
        portfolio = make_portfolio(cash=Decimal("1899.90"), positions={"BTC/USD": Decimal("0.002")})
        fill = make_fill(
            symbol="BTC/USD",
            side=Side.SELL,
            qty=Decimal("0.002"),
            price=Decimal("60000"),
            fee=Decimal("0.12"),
        )
        portfolio.apply_fill(fill)
        self.assertEqual(portfolio.cash, Decimal("2019.78"))
        self.assertEqual(portfolio.position_qty("BTC/USD"), Decimal("0"))

    def test_equity_matches_cash_plus_position_value(self) -> None:
        portfolio = make_portfolio(
            cash=Decimal("1000"),
            positions={"BTC/USD": Decimal("0.5")},
            last_prices={"BTC/USD": Decimal("60000")},
        )
        self.assertEqual(portfolio.equity(), Decimal("31000"))

    def test_equity_accepts_explicit_prices(self) -> None:
        portfolio = make_portfolio(cash=Decimal("1000"), positions={"BTC/USD": Decimal("0.5")})
        self.assertEqual(portfolio.equity({"BTC/USD": Decimal("40000")}), Decimal("21000"))

    def test_equity_ignores_symbols_without_price(self) -> None:
        portfolio = make_portfolio(cash=Decimal("1000"), positions={"BTC/USD": Decimal("0.5")})
        self.assertEqual(portfolio.equity(), Decimal("1000"))

    def test_sell_more_than_position_rejected(self) -> None:
        portfolio = make_portfolio(cash=Decimal("1000"), positions={"BTC/USD": Decimal("0.001")})
        fill = make_fill(
            symbol="BTC/USD",
            side=Side.SELL,
            qty=Decimal("0.002"),
            price=Decimal("50000"),
            fee=Decimal("0.10"),
        )
        with self.assertRaises(ValueError):
            portfolio.apply_fill(fill)
        self.assertEqual(portfolio.cash, Decimal("1000"))
        self.assertEqual(portfolio.position_qty("BTC/USD"), Decimal("0.001"))


if __name__ == "__main__":
    unittest.main()
