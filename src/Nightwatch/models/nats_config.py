"""Defines the NatsConnectionConfig Pydantic model for shared NATS connection parameters."""

from pydantic import BaseModel, ConfigDict, Field


class NatsConnectionConfig(BaseModel):
    """Shared NATS connection parameters."""

    servers: list[str] = Field(default_factory=lambda: ["nats://127.0.0.1:4222"])
    allow_reconnect: bool = True
    max_reconnect_attempts: int = -1
    reconnect_time_wait: float = 0.2
    ping_interval: int = 10
    max_outstanding_pings: int = 2

    model_config = ConfigDict(str_max_length=255)
