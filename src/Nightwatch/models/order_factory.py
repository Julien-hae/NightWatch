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
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from prometheus_client import Counter
from pydantic import BaseModel, ConfigDict, Field

from Nightwatch.models.order import Order, Status
from Nightwatch.models.portfolio import Portfolio
from Nightwatch.models.signal import Side, Signal

LOGGER = logging.getLogger(__name__)


class OrderFactoryConfig(BaseModel):
    """Configuration for the order factory's sizing rule."""

    order_notional: Decimal = Field(gt=0)

    model_config = ConfigDict(str_max_length=255)


class SignalDeduplicator:
    """In-memory tracker that suppresses orders for already-processed signal ids.

    A signal id is recorded via :meth:`mark_processed` after an order has been
    created. Subsequent calls to :meth:`is_duplicate` for the same id return
    ``True`` and (optionally) increment a ``duplicates_total`` Prometheus
    counter so callers can monitor duplication.
    """

    def __init__(self, duplicates_counter: Counter | None = None) -> None:
        """Initialise an empty deduplicator.

        Args:
            duplicates_counter: Optional Prometheus counter incremented each
                time a duplicate signal id is observed.
        """
        self._processed: set[uuid.UUID] = set()
        self._duplicates_counter = duplicates_counter

    def is_duplicate(self, signal_id: uuid.UUID) -> bool:
        """Return ``True`` if ``signal_id`` has already been marked as processed."""
        duplicate = signal_id in self._processed
        if duplicate and self._duplicates_counter is not None:
            self._duplicates_counter.inc()
        return duplicate

    def mark_processed(self, signal_id: uuid.UUID) -> None:
        """Record ``signal_id`` as processed so future occurrences are duplicates."""
        self._processed.add(signal_id)


def create_order_from_signal(
    signal: Signal,
    portfolio: Portfolio,
    config: OrderFactoryConfig,
    deduplicator: SignalDeduplicator | None = None,
) -> Order | None:
    """Build an :class:`Order` from an approved signal using the v0 sizing rule.

    Args:
        signal: The approved trading signal to convert.
        portfolio: Current portfolio state (positions and last prices).
        config: Sizing configuration (notional per order).
        deduplicator: Optional in-memory tracker preventing duplicate orders
            from being created for the same ``signal.uid``.

    Returns:
        A new :class:`Order` in ``NEW`` status, or ``None`` if the signal is a
        duplicate, or if a SELL signal was received but no position is currently
        held for the symbol.

    Raises:
        ValueError: If no last price is known for ``signal.symbol`` or the
            last price is not positive for a BUY signal, and a quantity therefore cannot be
            computed safely.
    """
    if deduplicator is not None and deduplicator.is_duplicate(signal.uid):
        LOGGER.info("duplicate signal %s for %s ignored", signal.uid, signal.symbol)
        return None

    last_price = portfolio.last_price(signal.symbol)
    if last_price is None:
        raise ValueError(f"Cannot size order for {signal.symbol}: no last price available")
    if signal.side is Side.BUY:
        if last_price <= 0:
            raise ValueError(f"Cannot size order for {signal.symbol}: last price must be positive, got {last_price}")
        qty = config.order_notional / last_price
    else:
        qty = portfolio.position_qty(signal.symbol)
        if qty <= 0:
            LOGGER.info("SELL signal %s for %s ignored: no position held", signal.uid, signal.symbol)
            return None

    order = Order(
        side=signal.side,
        symbol=signal.symbol,
        signal_id=signal.uid,
        qty=qty,
        status=Status.NEW,
        created_at=datetime.now(timezone.utc),
    )
    if deduplicator is not None:
        deduplicator.mark_processed(signal.uid)
    return order
