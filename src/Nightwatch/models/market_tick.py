"""Define the MarketTick model for representing market data ticks."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MarketTick(BaseModel):
    """Model to represent a market tick."""

    uid: uuid.UUID = Field(default_factory=uuid.uuid4)
    timestamp: datetime
    symbol: str = Field(min_length=1)
    price: Decimal = Field(ge=0)
    source: str
    schema_version: int

    model_config = ConfigDict(str_max_length=255)

    @field_validator("symbol")
    @classmethod
    def symbol_not_blank(cls, v: str) -> str:
        """Ensure that the symbol is not blank or just whitespace."""
        if not v.strip():
            raise ValueError("symbol must not be blank")
        return v
