"""Define the Portfolio model used for sizing decisions."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class Portfolio(BaseModel):
    """Lightweight, in-memory view of currently held positions and last known prices.

    This is intentionally minimal for v0: it exposes per-symbol position quantities
    and the last observed market price. Components (e.g. the order factory) can
    consume this state to make sizing decisions without depending on a full
    accounting subsystem.
    """

    positions: dict[str, Decimal] = Field(default_factory=dict)
    last_prices: dict[str, Decimal] = Field(default_factory=dict)

    model_config = ConfigDict(str_max_length=255)

    def position_qty(self, symbol: str) -> Decimal:
        """Return the currently held quantity for a symbol, or zero if none is held."""
        return self.positions.get(symbol, Decimal("0"))

    def last_price(self, symbol: str) -> Decimal | None:
        """Return the last observed price for a symbol, or ``None`` if unknown."""
        return self.last_prices.get(symbol)
