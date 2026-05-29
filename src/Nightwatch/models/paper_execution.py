"""Paper trading execution: simulate order fills at the latest tick price."""

from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from Nightwatch.models.fill import Fill
from Nightwatch.models.order import Order, Status


class PercentageFeeModel(BaseModel):
    """Fee model that charges a percentage of the trade notional.

    Attributes:
        rate: Fee rate applied to ``qty * price`` (e.g. ``Decimal("0.001")`` for 0.1%).
    """

    rate: Decimal = Field(ge=0)

    model_config = ConfigDict(str_max_length=255)

    def calculate(self, qty: Decimal, price: Decimal) -> Decimal:
        """Compute the fee for a trade of ``qty`` units at ``price``.

        Args:
            qty: Traded quantity.
            price: Trade price per unit.

        Returns:
            The fee as ``qty * price * rate``.
        """
        return qty * price * self.rate


def paper_execute(order: Order, last_price: Decimal, fee_model: PercentageFeeModel) -> Fill:
    """Simulate immediate execution of an order at the latest tick price.

    Args:
        order: The order to execute.
        last_price: The latest market tick price used as the fill price.
        fee_model: Fee model used to compute the trading fee.

    Returns:
        A :class:`Fill` representing the simulated execution. The order's
        ``status`` is transitioned to :attr:`Status.FILLED` as a side effect.

    Raises:
        ValueError: If ``last_price`` is not strictly positive.
    """
    if last_price <= 0:
        raise ValueError("last_price must be strictly positive")
    fee = fee_model.calculate(order.qty, last_price)
    fill = Fill(
        side=order.side,
        symbol=order.symbol,
        order_id=order.order_id,
        qty=order.qty,
        price=last_price,
        fee=fee,
        ts=datetime.now(timezone.utc),
    )
    order.status = Status.FILLED
    return fill
