"""Convert approved trading signals into executable :class:`Order` instances.

This module implements a simple, configurable position-sizing rule (v0):

* For ``BUY`` signals, the order quantity is derived from a fixed quote
  notional divided by the last known market price.
* For ``SELL`` signals, the order liquidates the full currently held
  position for the symbol.

If no last price is available for the symbol, no order can be sized and a
:class:`ValueError` is raised.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from Nightwatch.models.order import Order, Status
from Nightwatch.models.portfolio import Portfolio
from Nightwatch.models.signal import Side, Signal

LOGGER = logging.getLogger(__name__)


class OrderFactoryConfig(BaseModel):
    """Configuration for the order factory's sizing rule."""

    order_notional: Decimal = Field(gt=0)

    model_config = ConfigDict(str_max_length=255)


def create_order_from_signal(
    signal: Signal,
    portfolio: Portfolio,
    config: OrderFactoryConfig,
) -> Order | None:
    """Build an :class:`Order` from an approved signal using the v0 sizing rule.

    Args:
        signal: The approved trading signal to convert.
        portfolio: Current portfolio state (positions and last prices).
        config: Sizing configuration (notional per order).

    Returns:
        A new :class:`Order` in ``NEW`` status, or ``None`` if a SELL signal
        was received but no position is currently held for the symbol.

    Raises:
        ValueError: If no last price is known for ``signal.symbol`` or the
            last price is not positive, and a quantity therefore cannot be
            computed safely.
    """
    last_price = portfolio.last_price(signal.symbol)
    if last_price is None:
        raise ValueError(f"Cannot size order for {signal.symbol}: no last price available")
    if last_price <= 0:
        raise ValueError(f"Cannot size order for {signal.symbol}: last price must be positive, got {last_price}")

    if signal.side is Side.BUY:
        qty = config.order_notional / last_price
    else:
        qty = portfolio.position_qty(signal.symbol)
        if qty <= 0:
            LOGGER.info("SELL signal %s for %s ignored: no position held", signal.uid, signal.symbol)
            return None

    return Order(
        side=signal.side,
        symbol=signal.symbol,
        signal_id=signal.uid,
        qty=qty,
        status=Status.NEW,
        created_at=datetime.now(timezone.utc),
    )
