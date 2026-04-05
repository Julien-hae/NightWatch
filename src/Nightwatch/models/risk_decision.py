"""Model to represent a risk decision."""

import uuid

from pydantic import BaseModel, Field


class RiskDecision(BaseModel):
    """Model to represent a risk decision."""

    allowed: bool
    reason: str | None
    rule: str | None
    symbol: str = Field(min_length=1)
    signal_id: uuid.UUID
