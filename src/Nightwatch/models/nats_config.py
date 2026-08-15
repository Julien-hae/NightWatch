"""Defines the NatsConnectionConfig Pydantic model for shared NATS connection parameters."""

import os

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

load_dotenv("credentials.env")


def _default_servers() -> list[str]:
    """Return NATS server URLs from the NATS_SERVERS env var (comma-separated) or localhost default."""
    env = os.environ.get("NATS_SERVERS")
    if env:
        return [s.strip() for s in env.split(",") if s.strip()]
    return ["nats://127.0.0.1:4222"]


class NatsConnectionConfig(BaseModel):
    """Shared NATS connection parameters with optional TLS and auth support.

    Authentication secrets are loaded from environment variables and should never be committed.
    Supported env vars:
        NATS_SERVERS       – comma-separated list of NATS URLs (e.g. "tls://host:4222")
        NATS_TOKEN         – authentication token

    NKey auth is not implemented yet — the ``nkeys_seed`` field below is commented
    out as a placeholder; do not document ``NATS_NKEY_SEED`` as supported until it is.
    """

    servers: list[str] = Field(default_factory=_default_servers)
    allow_reconnect: bool = True
    max_reconnect_attempts: int = -1
    reconnect_time_wait: float = 0.2
    ping_interval: int = 10
    max_outstanding_pings: int = 2
    token: str | None = Field(default_factory=lambda: os.environ.get("NATS_TOKEN", None))
    # nkeys_seed: str | None = Field(default_factory=lambda: os.environ.get("NATS_NKEY_SEED"))  # not yet implemented

    model_config = ConfigDict(str_max_length=255)
