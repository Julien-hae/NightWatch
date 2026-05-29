"""Unit tests for :mod:`Nightwatch.models.order_factory`."""

import unittest
from decimal import Decimal

from Nightwatch.metrics import NightwatchMetrics
from Nightwatch.models.order import Status
from Nightwatch.models.order_factory import OrderFactoryConfig, SignalDeduplicator, create_order_from_signal
from Nightwatch.models.signal import Side
from tests.fixtures.portfolio_factory import make_portfolio
from tests.fixtures.signal_factory import make_signal


class TestOrderFactoryConfig(unittest.TestCase):
    """Validation tests for the OrderFactoryConfig model."""

    def test_order_notional_must_be_positive(self) -> None:
        """Test that order_notional must be a positive Decimal."""
        with self.assertRaises(ValueError):
            OrderFactoryConfig(order_notional=Decimal("0"))
        with self.assertRaises(ValueError):
            OrderFactoryConfig(order_notional=Decimal("-1"))


class TestCreateOrderFromSignalBuy(unittest.TestCase):
    """Tests for BUY signal handling."""

    def setUp(self) -> None:
        self.config = OrderFactoryConfig(order_notional=Decimal("100"))
        self.portfolio = make_portfolio(last_prices={"BTC/USD": Decimal("50000")})
        self.signal = make_signal(symbol="BTC/USD", side=Side.BUY)

    def test_buy_creates_order_with_computed_qty(self) -> None:
        """Test that a BUY signal creates an Order with the correct computed quantity."""
        order = create_order_from_signal(self.signal, self.portfolio, self.config)

        self.assertIsNotNone(order)
        assert order is not None
        self.assertEqual(order.side, Side.BUY)
        self.assertEqual(order.symbol, "BTC/USD")
        self.assertEqual(order.signal_id, self.signal.uid)
        self.assertEqual(order.qty, Decimal("100") / Decimal("50000"))
        self.assertEqual(order.status, Status.NEW)
        self.assertIsNotNone(order.created_at.tzinfo)

    def test_buy_uses_decimal_division_precision(self) -> None:
        """Test that a BUY signal uses Decimal division precision."""
        portfolio = make_portfolio(last_prices={"BTC/USD": Decimal("3")})
        config = OrderFactoryConfig(order_notional=Decimal("10"))

        order = create_order_from_signal(self.signal, portfolio, config)

        assert order is not None
        self.assertEqual(order.qty, Decimal("10") / Decimal("3"))


class TestCreateOrderFromSignalSell(unittest.TestCase):
    """Tests for SELL signal handling (v0: sell entire position)."""

    def setUp(self) -> None:
        self.config = OrderFactoryConfig(order_notional=Decimal("100"))
        self.signal = make_signal(symbol="BTC/USD", side=Side.SELL)

    def test_sell_creates_order_for_full_position(self) -> None:
        """Test that a SELL signal creates an Order for the full position."""
        portfolio = make_portfolio(
            positions={"BTC/USD": Decimal("0.5")},
            last_prices={"BTC/USD": Decimal("50000")},
        )

        order = create_order_from_signal(self.signal, portfolio, self.config)

        assert order is not None
        self.assertEqual(order.side, Side.SELL)
        self.assertEqual(order.qty, Decimal("0.5"))
        self.assertEqual(order.signal_id, self.signal.uid)
        self.assertEqual(order.status, Status.NEW)

    def test_sell_returns_none_when_no_position_held(self) -> None:
        """Test that a SELL signal returns None when no position is held."""
        portfolio = make_portfolio(last_prices={"BTC/USD": Decimal("50000")})

        order = create_order_from_signal(self.signal, portfolio, self.config)

        self.assertIsNone(order)


class TestCreateOrderFromSignalNoPrice(unittest.TestCase):
    """Tests for handling missing market price."""

    def test_buy_without_price_raises(self) -> None:
        """Test that a BUY signal raises an error when no price is available."""
        config = OrderFactoryConfig(order_notional=Decimal("100"))
        portfolio = make_portfolio()
        signal = make_signal(symbol="BTC/USD", side=Side.BUY)

        with self.assertRaises(ValueError):
            create_order_from_signal(signal, portfolio, config)

    def test_sell_without_price_raises(self) -> None:
        """Test that a SELL signal raises an error when no price is available."""
        config = OrderFactoryConfig(order_notional=Decimal("100"))
        portfolio = make_portfolio(positions={"BTC/USD": Decimal("0.5")})
        signal = make_signal(symbol="BTC/USD", side=Side.SELL)

        with self.assertRaises(ValueError):
            create_order_from_signal(signal, portfolio, config)


class TestCreateOrderFromSignalDeduplication(unittest.TestCase):
    """Tests for idempotent processing of signals via SignalDeduplicator."""

    def setUp(self) -> None:
        self.config = OrderFactoryConfig(order_notional=Decimal("100"))
        self.portfolio = make_portfolio(last_prices={"BTC/USD": Decimal("50000")})
        self.signal = make_signal(symbol="BTC/USD", side=Side.BUY)

    def test_duplicate_signal_returns_none(self) -> None:
        deduplicator = SignalDeduplicator()

        first = create_order_from_signal(self.signal, self.portfolio, self.config, deduplicator)
        second = create_order_from_signal(self.signal, self.portfolio, self.config, deduplicator)

        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_distinct_signals_both_create_orders(self) -> None:
        deduplicator = SignalDeduplicator()
        other = make_signal(symbol="BTC/USD", side=Side.BUY)

        first = create_order_from_signal(self.signal, self.portfolio, self.config, deduplicator)
        second = create_order_from_signal(other, self.portfolio, self.config, deduplicator)

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        assert first is not None and second is not None
        self.assertNotEqual(first.signal_id, second.signal_id)

    def test_duplicate_increments_duplicates_counter(self) -> None:
        metrics = NightwatchMetrics()
        deduplicator = SignalDeduplicator(duplicates_counter=metrics.signals_duplicates_total)

        create_order_from_signal(self.signal, self.portfolio, self.config, deduplicator)
        create_order_from_signal(self.signal, self.portfolio, self.config, deduplicator)
        create_order_from_signal(self.signal, self.portfolio, self.config, deduplicator)

        self.assertEqual(metrics.signals_duplicates_total._value.get(), 2.0)

    def test_failed_order_creation_does_not_mark_processed(self) -> None:
        deduplicator = SignalDeduplicator()
        portfolio_without_price = make_portfolio()

        with self.assertRaises(ValueError):
            create_order_from_signal(self.signal, portfolio_without_price, self.config, deduplicator)

        order = create_order_from_signal(self.signal, self.portfolio, self.config, deduplicator)
        self.assertIsNotNone(order)


if __name__ == "__main__":
    unittest.main()
