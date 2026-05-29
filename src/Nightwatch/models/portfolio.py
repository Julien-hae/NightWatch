"""Define the Portfolio model used for sizing decisions."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from Nightwatch.models.fill import Fill
from Nightwatch.models.signal import Side


class Portfolio(BaseModel):
    """In-memory view of cash, positions and last observed prices.

    Tracks free cash, per-symbol position quantities, and the latest known
    market price per symbol. Fills are applied via :meth:`apply_fill`, which
    mutates ``cash`` and ``positions`` according to the BUY/SELL rules.
    """

    cash: Decimal = Field(default=Decimal("0"))
    positions: dict[str, Decimal] = Field(default_factory=dict)
    last_prices: dict[str, Decimal] = Field(default_factory=dict)

    model_config = ConfigDict(str_max_length=255)

    def position_qty(self, symbol: str) -> Decimal:
        """Return the currently held quantity for a symbol, or zero if none is held."""
        return self.positions.get(symbol, Decimal("0"))

    def last_price(self, symbol: str) -> Decimal | None:
        """Return the last observed price for a symbol, or ``None`` if unknown."""
        return self.last_prices.get(symbol)

    def equity(self, last_prices: dict[str, Decimal] | None = None) -> Decimal:
        """Return total equity as cash plus the market value of all positions.

        Args:
            last_prices: Optional override of per-symbol prices. When omitted,
                the portfolio's own ``last_prices`` are used. Symbols without a
                known price contribute zero to the position value.

        Returns:
            ``cash + sum(qty * price)`` over all held positions.
        """
        prices = self.last_prices if last_prices is None else last_prices
        position_value = Decimal("0")
        for symbol, qty in self.positions.items():
            price = prices.get(symbol)
            if price is not None:
                position_value += qty * price
        return self.cash + position_value

    def apply_fill(self, fill: Fill) -> None:
        """Update cash and position state from a fill.

        BUY decreases cash by ``qty * price + fee`` and increases the position.
        SELL increases cash by ``qty * price - fee`` and decreases the position.
        The fill's price is also recorded as the latest known price for the symbol.

        Args:
            fill: The fill to apply.

        Raises:
            ValueError: If a SELL would reduce the position below zero.
        """
        notional = fill.qty * fill.price
        current_qty = self.position_qty(fill.symbol)
        if fill.side is Side.BUY:
            self.cash -= notional + fill.fee
            self.positions[fill.symbol] = current_qty + fill.qty
        else:
            if fill.qty > current_qty:
                raise ValueError(f"cannot sell {fill.qty} of {fill.symbol}: only {current_qty} held")
            self.cash += notional - fill.fee
            self.positions[fill.symbol] = current_qty - fill.qty
        self.last_prices[fill.symbol] = fill.price
