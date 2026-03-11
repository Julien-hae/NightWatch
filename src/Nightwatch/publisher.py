"""Defines the MarketTickPublisher class for publishing MarketTick data to a NATS server."""

import logging

from Nightwatch.models.market_tick import MarketTick
from Nightwatch.models.nats_connection import normalize_symbol
from Nightwatch.nats_connection import NatsConnector

LOGGER = logging.getLogger(__name__)


class MarketTickPublisher(NatsConnector):
    """Publisher for MarketTick data to a NATS server."""

    @staticmethod
    def subject_for(tick: MarketTick) -> str:
        """Return the NATS subject for a given MarketTick."""
        return f"market.tick.{normalize_symbol(tick.symbol)}"

    async def publish(self, tick: MarketTick, *, flush: bool = True) -> str:
        """Publish a MarketTick to the appropriate subject. Returns the subject used."""
        if not self.client.is_connected:
            LOGGER.warning("NATS publisher is not connected. Calling connect(),")
            await self.connect()

        subject = self.subject_for(tick)
        payload = tick.model_dump_json().encode("utf-8")
        await self.client.publish(subject, payload)
        if flush:
            await self.client.flush(timeout=5)
        if self._metrics:
            self._metrics.ticks_published_total.labels(symbol=tick.symbol).inc()
        return subject
