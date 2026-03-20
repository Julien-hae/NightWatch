"""Define the Signal model for representing Signals."""

import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Side(str, Enum):
    """Enum to represent the side of a trading signal, either BUY or SELL."""

    BUY = "BUY"
    SELL = "SELL"


class Signal(BaseModel):
    """Model to represent a trading signal."""

    uid: uuid.UUID = Field(default_factory=uuid.uuid4)
    timestamp: datetime
    symbol: str = Field(min_length=1)
    side: Side
    strength: float = Field(ge=0)
    strategy: str = Field(min_length=1)
    rationale: dict[str, Union[float, Decimal]] = Field(default_factory=dict)
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
