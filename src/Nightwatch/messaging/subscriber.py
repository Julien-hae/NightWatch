"""Defines the MarketTickSubscriber class for subscribing to MarketTick data from a NATS server."""

import logging
from typing import Any, Awaitable, Callable

from nats.aio.msg import Msg
from nats.aio.subscription import Subscription
from pydantic import ValidationError

from Nightwatch.messaging.nats_connection import NatsConnector
from Nightwatch.metrics import NightwatchMetrics
from Nightwatch.models.market_tick import MarketTick
from Nightwatch.models.nats_config import NatsConnectionConfig

LOGGER = logging.getLogger(__name__)


class MarketTickSubscriber(NatsConnector):
    """Subscriber for MarketTick data from a NATS server."""

    def __init__(self, config: NatsConnectionConfig | None = None, metrics: NightwatchMetrics | None = None) -> None:
        """Initialize the MarketTickSubscriber with NATS connection parameters."""
        super().__init__(config=config, metrics=metrics)
        self._subscription: Subscription | None = None

    async def subscribe(
        self,
        subject: str,
        cb: Callable[[MarketTick], Awaitable[Any]] | None = None,
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
                return
            if self._metrics:
                self._metrics.ticks_consumed_total.labels(symbol=tick.symbol).inc()
            if cb is not None:
                await cb(tick)

        self._subscription = await self._nc.subscribe(subject=subject, cb=_handler)
        await self.client.flush()
