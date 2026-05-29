"""Factory functions to create test instances of the Fill model."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from Nightwatch.models.fill import Fill  # type: ignore[import-untyped]
from Nightwatch.models.signal import Side  # type: ignore[import-untyped]


def make_fill(
    symbol: str = "BTC/USD",
    side: Side = Side.BUY,
    order_id: uuid.UUID | None = None,
    qty: Decimal = Decimal("1.0"),
    price: Decimal = Decimal("50000.0"),
    fee: Decimal = Decimal("0.0"),
    **kwargs: Any,
) -> Fill:
    """Helper function to create a Fill with default values for testing."""
    if order_id is None:
        order_id = uuid.uuid4()
    return Fill(
        symbol=symbol,
        side=side,
        order_id=order_id,
        qty=qty,
        price=price,
        fee=fee,
        ts=kwargs.pop("ts", datetime.now(timezone.utc)),
        **kwargs,
    )
