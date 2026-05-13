"""Define the Fill model for representing market fills."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from Nightwatch.models.signal import Side


class Fill(BaseModel):
    """Model to represent a market fill."""

    fill_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    side: Side
    symbol: str = Field(min_length=1)
    order_id: uuid.UUID
    qty: Decimal = Field(gt=0)
    price: Decimal = Field(gt=0)
    fee: Decimal = Field(ge=0)
    ts: datetime

    model_config = ConfigDict(str_max_length=255)

    @field_validator("symbol")
    @classmethod
    def symbol_not_blank(cls, v: str) -> str:
        """Ensure that the symbol is not blank or just whitespace."""
        if not v.strip():
            raise ValueError("symbol must not be blank")
        return v

    @field_validator("ts")
    @classmethod
    def ts_must_be_timezone_aware(cls, v: datetime) -> datetime:
        """Require timezone-aware ts and normalize them to UTC."""
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("ts must be timezone-aware")
        return v.astimezone(timezone.utc)
