"""Defines the NatsConnector class for connecting to a NATS server."""

import logging
from typing import Any, Awaitable, Callable

from nats.aio.client import Client as NatsClient

from Nightwatch.metrics import NightwatchMetrics
from Nightwatch.models.nats_config import NatsConnectionConfig

LOGGER = logging.getLogger(__name__)


class NatsConnector:
    """Connector for NATS server."""

    def __init__(self, config: NatsConnectionConfig | None = None, metrics: NightwatchMetrics | None = None) -> None:
        """Initialize the NatsConnector with NATS connection parameters."""
        self._nc: NatsClient = NatsClient()
        self._config = config or NatsConnectionConfig()
        self._metrics = metrics

    async def connect(
        self,
        *,
        on_disconnected: Callable[[], Awaitable[Any]] | None = None,
        on_reconnected: Callable[[], Awaitable[Any]] | None = None,
    ) -> None:
        """Connect to the NATS server with optional callbacks for disconnect/reconnect events."""

        async def _disconnected_cb() -> None:
            """Internal callback for NATS disconnection events."""
            if on_disconnected:
                await on_disconnected()

        async def _reconnected_cb() -> None:
            """Internal callback for NATS reconnection events."""
            if on_reconnected:
                await on_reconnected()

        opts = self._config.model_dump()
        await self._nc.connect(
            **opts,
            disconnected_cb=_disconnected_cb if on_disconnected else None,
            reconnected_cb=_reconnected_cb if on_reconnected else None,
        )

    async def close(self) -> None:
        """Close the connection to the NATS server."""
        await self._nc.drain()

    @property
    def client(self) -> NatsClient:
        """Get the underlying NATS client instance."""
        return self._nc
