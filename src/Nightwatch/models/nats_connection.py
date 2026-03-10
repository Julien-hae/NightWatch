"""Defines the NatsConnectionConfig dataclass for shared NATS connection parameters."""

import re
from typing import List

from pydantic import BaseModel, ConfigDict


class NatsConnectionConfig(BaseModel):
    """Shared NATS connection parameters."""

    servers: List[str] = ["nats://127.0.0.1:4222"]
    allow_reconnect: bool = True
    max_reconnect_attempts: int = -1
    reconnect_time_wait: float = 0.2
    ping_interval: int = 10
    max_outstanding_pings: int = 2

    model_config = ConfigDict(str_max_length=255)


def normalize_symbol(symbol: str) -> str:
    """Normalize a symbol string to be used in NATS subjects (e.g., "BTC/USD" -> "BTCUSD")."""
    return re.sub(r"[^A-Za-z0-9]", "", symbol).upper()
