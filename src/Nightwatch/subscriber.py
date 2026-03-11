"""Defines the MarketTickSubscriber class for subscribing to MarketTick data from a NATS server."""

import logging
from typing import Any, Awaitable, Callable, Optional

from nats.aio.client import Client as NatsClient
from nats.aio.msg import Msg
from pydantic import ValidationError

from Nightwatch.metrics import NightwatchMetrics
from Nightwatch.models.market_tick import MarketTick
from Nightwatch.models.nats_connection import NatsConnectionConfig

LOGGER = logging.getLogger(__name__)


class MarketTickSubscriber:
    """Subscriber for MarketTick data from a NATS server."""

    def __init__(self, config: Optional[NatsConnectionConfig] = None, metrics: Optional[NightwatchMetrics] = None) -> None:
        """Initialize the MarketTickSubscriber with NATS connection parameters."""
        self._nc: NatsClient = NatsClient()
        self._config = config or NatsConnectionConfig()
        self._metrics = metrics

    async def connect(
        self,
        *,
        on_disconnected: Optional[Callable[[], Awaitable[Any]]] = None,
        on_reconnected: Optional[Callable[[], Awaitable[Any]]] = None,
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

        await self._nc.connect(
            **self._config.model_dump(),
            disconnected_cb=_disconnected_cb if on_disconnected else None,
            reconnected_cb=_reconnected_cb if on_reconnected else None,
        )

    async def close(self) -> None:
        """Close the connection to the NATS server."""
        await self._nc.drain()

    async def subscribe(
        self,
        subject: str,
        cb: Optional[Callable[[MarketTick], Awaitable[Any]]] = None,
    ) -> None:
        """Subscribe to a subject, calling cb with each received MarketTick."""
        if not self._nc.is_connected:
            LOGGER.warning("NATS subscriber is not connected. Calling connect(),")
            await self.connect()

        async def _handler(msg: Msg) -> None:
            try:
                tick = MarketTick.model_validate_json(msg.data)
            except ValidationError as exc:
                if self._metrics is not None:
                    self._metrics.parse_errors_total.inc()
                LOGGER.error("Error parsing ticker message %s. exc=%s", msg, exc)
            if self._metrics:
                self._metrics.ticks_consumed_total.labels(symbol=tick.symbol).inc()
            if cb is not None:
                await cb(tick)

        await self._nc.subscribe(subject=subject, cb=_handler)
        await self._nc.flush()

    @property
    def client(self) -> NatsClient:
        """Get the underlying NATS client instance."""
        return self._nc
