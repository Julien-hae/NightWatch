"""Defines the MarketTickPublisher class for publishing MarketTick data to a NATS server."""

import logging

from Nightwatch.common.utils import normalize_symbol
from Nightwatch.messaging.nats_connection import NatsConnector
from Nightwatch.models.market_tick import MarketTick

LOGGER = logging.getLogger(__name__)

MAX_PAYLOAD_BYTES = 1_048_576


class PayloadTooLargeError(Exception):
    """Raised when a serialized MarketTick exceeds the max allowed NATS payload size."""


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

        if len(payload) > MAX_PAYLOAD_BYTES:
            raise PayloadTooLargeError(f"Payload size {len(payload)} bytes exceeds max {MAX_PAYLOAD_BYTES} bytes")

        await self.client.publish(subject, payload)
        if flush:
            await self.client.flush(timeout=5)
        if self._metrics:
            self._metrics.ticks_published_total.labels(symbol=tick.symbol).inc()
        return subject
