"""Defines the MarketTickPublisher class for publishing MarketTick data to a NATS server."""

import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from nats.aio.client import Client as NatsClient

from Nightwatch.models.market_tick import MarketTick


def normalize_symbol(symbol: str) -> str:
    """Normalize a symbol string to be used in NATS subjects (e.g., "BTC/USD" -> "BTCUSD")."""
    return re.sub(r"[^A-Za-z0-9]", "", symbol).upper()


class MarketTickPublisher:
    """Publisher for MarketTick data to a NATS server."""

    def __init__(
        self,
        servers: Sequence[str] = ("nats://127.0.0.1:4222",),
        allow_reconnect: bool = True,
        max_reconnect_attempts: int = -1,
        reconnect_time_wait: float = 0.2,
        ping_interval: int = 10,
        max_outstanding_pings: int = 2,
    ) -> None:
        """Initialize the MarketTickPublisher with NATS connection parameters."""
        self._servers: List[str] = list(servers)
        self._nc: NatsClient = NatsClient()
        self._connect_kwargs: Dict[str, Any] = dict(
            servers=self._servers,
            allow_reconnect=allow_reconnect,
            max_reconnect_attempts=max_reconnect_attempts,
            reconnect_time_wait=reconnect_time_wait,
            ping_interval=ping_interval,
            max_outstanding_pings=max_outstanding_pings,
        )

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
            **self._connect_kwargs,
            disconnected_cb=_disconnected_cb if on_disconnected else None,
            reconnected_cb=_reconnected_cb if on_reconnected else None,
        )

    async def close(self) -> None:
        """Close the connection to the NATS server."""
        await self._nc.drain()

    @staticmethod
    def subject_for(tick: MarketTick) -> str:
        """Return the NATS subject for a given MarketTick."""
        return f"market.tick.{normalize_symbol(tick.symbol)}"

    async def publish(self, tick: MarketTick, *, flush: bool = True) -> str:
        """Publish a MarketTick to the appropriate subject. Returns the subject used."""
        subject = self.subject_for(tick)
        payload = tick.json().encode("utf-8")
        await self._nc.publish(subject, payload)
        if flush:
            await self._nc.flush(timeout=2)
        return subject

    @property
    def client(self) -> NatsClient:
        """Get the underlying NATS client instance."""
        return self._nc
