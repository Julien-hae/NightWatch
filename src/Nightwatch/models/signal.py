"""Define the Signal model for representing Signals."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Signal(BaseModel):
    """Model to represent a trading signal."""

    uid: uuid.UUID = Field(default_factory=uuid.uuid4)
    timestamp: datetime
    symbol: str = Field(min_length=1)
    side: str = Field(min_length=1)
    strength: float = Field(ge=0)
    strategy: str = Field(min_length=1)
    rationale: dict[str, float] = Field(default_factory=dict)
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

    @field_validator("side")
    @classmethod
    def only_buy_or_sell_side(cls, v: str) -> str:
        """Ensure that the side is either 'BUY' or 'SELL'."""
        if v not in ["BUY", "SELL"]:
            raise ValueError("side must be 'BUY' or 'SELL'")
        return v
