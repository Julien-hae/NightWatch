"""Define the Order model for representing market orders."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from Nightwatch.models.signal import Side


class Status(str, Enum):
    """Enum to represent the status of a market order."""

    NEW = "NEW"
    FILLED = "FILLED"


class Order(BaseModel):
    """Model to represent a market order."""

    order_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    side: Side
    symbol: str = Field(min_length=1)
    signal_id: uuid.UUID
    qty: Decimal = Field(gt=0)
    status: Status
    created_at: datetime

    model_config = ConfigDict(str_max_length=255)

    @field_validator("symbol")
    @classmethod
    def symbol_not_blank(cls, v: str) -> str:
        """Ensure that the symbol is not blank or just whitespace."""
        if not v.strip():
            raise ValueError("symbol must not be blank")
        return v

    @field_validator("created_at")
    @classmethod
    def created_at_must_be_timezone_aware(cls, v: datetime) -> datetime:
        """Require timezone-aware created_at and normalize them to UTC."""
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return v.astimezone(timezone.utc)
