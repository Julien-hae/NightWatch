"""Model to represent a bot control event, such as killing a bot for a specific reason at a certain timestamp."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BotControlEvent(BaseModel):
    """Model to represent a bot control event."""

    kill: bool
    timestamp: datetime
    reason: str = Field(min_length=1)

    model_config = ConfigDict(str_max_length=255)

    @field_validator("kill", mode="before")
    @classmethod
    def kill_must_be_bool(cls, v: Any) -> bool:
        """Ensure that kill is strictly a bool (not int, str, etc)."""
        if not isinstance(v, bool):
            raise ValueError("kill must be a boolean (True or False), not %r" % type(v).__name__)
        return v

    @field_validator("reason")
    @classmethod
    def reason_not_blank(cls, v: str) -> str:
        """Ensure that the reason is not blank or just whitespace."""
        if not v.strip():
            raise ValueError("reason must not be blank")
        return v
