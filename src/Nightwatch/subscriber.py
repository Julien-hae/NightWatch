"""Defines the MarketTickSubscriber class for subscribing to MarketTick data from a NATS server."""

import logging
from typing import Any, Awaitable, Callable, Optional

from nats.aio.msg import Msg
from nats.aio.subscription import Subscription
from pydantic import ValidationError

from Nightwatch.metrics import NightwatchMetrics
from Nightwatch.models.market_tick import MarketTick
from Nightwatch.models.nats_connection import NatsConnectionConfig
from Nightwatch.nats_connection import NatsConnector

LOGGER = logging.getLogger(__name__)


class MarketTickSubscriber(NatsConnector):
    """Subscriber for MarketTick data from a NATS server."""

    def __init__(self, config: Optional[NatsConnectionConfig] = None, metrics: Optional[NightwatchMetrics] = None) -> None:
        """Initialize the MarketTickSubscriber with NATS connection parameters."""
        super().__init__(config=config, metrics=metrics)
        self._subscription: Optional[Subscription] = None

    async def subscribe(
        self,
        subject: str,
        cb: Optional[Callable[[MarketTick], Awaitable[Any]]] = None,
    ) -> None:
        """Subscribe to a subject, calling cb with each received MarketTick."""
        if not self.client.is_connected:
            LOGGER.warning("NATS subscriber is not connected. Calling connect(),")
            await self.connect()
        if self._subscription is not None:
            await self._subscription.unsubscribe()

        async def _handler(msg: Msg) -> None:
            try:
                tick = MarketTick.model_validate_json(msg.data)
            except ValidationError as exc:
                if self._metrics is not None:
                    self._metrics.parse_errors_total.inc()
                LOGGER.error("Error parsing ticker message %s. exc=%s", msg, exc)
                raise
            if self._metrics:
                self._metrics.ticks_consumed_total.labels(symbol=tick.symbol).inc()
            if cb is not None:
                await cb(tick)

        self._subscription = await self._nc.subscribe(subject=subject, cb=_handler)
        await self._nc.flush()
