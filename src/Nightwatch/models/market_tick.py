"""Define the MarketTick model for representing market data ticks."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class MarketTick(BaseModel):
    """Model to represent a market tick."""

    uid: uuid.UUID = uuid.uuid4()
    timestamp: datetime
    symbol: str
    price: Decimal = Field(ge=0)
    source: str
    schema_version: int

    model_config = ConfigDict(str_max_length=255)
