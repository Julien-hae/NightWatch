"""Defines the MarketTickSubscriber class for subscribing to MarketTick data from a NATS server."""

from typing import Any, Awaitable, Callable, Optional

from nats.aio.client import Client as NatsClient
from nats.aio.msg import Msg

from Nightwatch.models.market_tick import MarketTick
from Nightwatch.models.nats_connection import NatsConnectionConfig


class MarketTickSubscriber:
    """Subscriber for MarketTick data from a NATS server."""

    def __init__(self, config: Optional[NatsConnectionConfig] = None) -> None:
        """Initialize the MarketTickSubscriber with NATS connection parameters."""
        self._nc: NatsClient = NatsClient()
        self._config = config or NatsConnectionConfig()

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

        async def _handler(msg: Msg) -> None:
            tick = MarketTick.model_validate_json(msg.data)
            if cb is not None:
                await cb(tick)

        await self._nc.subscribe(subject=subject, cb=_handler)
        await self._nc.flush()

    @property
    def client(self) -> NatsClient:
        """Get the underlying NATS client instance."""
        return self._nc
