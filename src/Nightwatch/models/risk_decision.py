"""Model to represent a risk decision."""

import uuid

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator


class RiskDecision(BaseModel):
    """Model to represent a risk decision."""

    allowed: bool
    reason: str | None = None
    rule: str | None = None
    symbol: str = Field(min_length=1)
    signal_id: uuid.UUID

    model_config = ConfigDict(str_max_length=255)

    @field_validator("symbol")
    @classmethod
    def symbol_not_blank(cls, v: str) -> str:
        """Ensure that the symbol is not blank or just whitespace."""
        if not v.strip():
            raise ValueError("symbol must not be blank")
        return v

    @field_validator("reason", "rule", mode="after")
    @classmethod
    def validate_reason_and_rule(cls, v: str | None, info: ValidationInfo) -> str | None:  # type: ignore[type-arg]
        """Ensure that reason and rule are set according to allowed."""
        allowed = info.data.get("allowed")
        if allowed is False and v is None:
            raise ValueError("reason and rule must be provided when allowed is False")
        if allowed is True and v is not None:
            raise ValueError("reason and rule must be None when allowed is True")
        return v

    @model_validator(mode="after")
    def reason_rule_consistent_with_allowed(self) -> "RiskDecision":
        """Ensure that reason and rule are set according to allowed."""
        if not self.allowed and (self.reason is None or self.rule is None):
            raise ValueError("reason and rule must be provided when allowed is False")
        if self.allowed and (self.reason is not None or self.rule is not None):
            raise ValueError("reason and rule must be None when allowed is True")
        return self
