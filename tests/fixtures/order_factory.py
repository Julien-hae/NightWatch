"""Factory functions to create test instances of the Order model."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from Nightwatch.models.order import Order, Status
from Nightwatch.models.signal import Side


def make_order(
    symbol: str = "BTC/USD",
    side: Side = Side.BUY,
    signal_id: uuid.UUID = uuid.uuid4(),
    qty: Decimal = Decimal("1.0"),
    status: Status = Status.NEW,
    **kwargs: Any,
) -> Order:
    """Helper function to create an Order with default values for testing."""
    return Order(
        symbol=symbol,
        side=side,
        signal_id=signal_id,
        qty=qty,
        status=status,
        created_at=kwargs.pop("created_at", datetime.now(timezone.utc)),
        **kwargs,
    )
