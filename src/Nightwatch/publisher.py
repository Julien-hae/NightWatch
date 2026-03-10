"""Defines the MarketTickPublisher class for publishing MarketTick data to a NATS server."""

from typing import Any, Awaitable, Callable, Optional

from nats.aio.client import Client as NatsClient

from Nightwatch.metrics import NightwatchMetrics
from Nightwatch.models.market_tick import MarketTick
from Nightwatch.models.nats_connection import NatsConnectionConfig, normalize_symbol


class MarketTickPublisher:
    """Publisher for MarketTick data to a NATS server."""

    def __init__(self, config: Optional[NatsConnectionConfig] = None, metrics: Optional[NightwatchMetrics] = None) -> None:
        """Initialize the MarketTickPublisher with NATS connection parameters."""
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

    @staticmethod
    def subject_for(tick: MarketTick) -> str:
        """Return the NATS subject for a given MarketTick."""
        return f"market.tick.{normalize_symbol(tick.symbol)}"

    async def publish(self, tick: MarketTick, *, flush: bool = True) -> str:
        """Publish a MarketTick to the appropriate subject. Returns the subject used."""
        subject = self.subject_for(tick)
        payload = tick.model_dump_json().encode("utf-8")
        await self._nc.publish(subject, payload)
        if flush:
            await self._nc.flush(timeout=5)
        if self._metrics:
            self._metrics.ticks_published_total.labels(symbol=tick.symbol).inc()
        return subject

    @property
    def client(self) -> NatsClient:
        """Get the underlying NATS client instance."""
        return self._nc
