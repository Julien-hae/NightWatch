"""Defines the ControlEventPublisher class for publishing BotControlEvent data via NATS JetStream."""

import logging

from nats.js.api import RetentionPolicy, StorageType, StreamConfig
from nats.js.errors import NotFoundError

from Nightwatch.messaging.nats_connection import NatsConnector
from Nightwatch.metrics.metrics import NightwatchMetrics
from Nightwatch.models.bot_control_event import BotControlEvent
from Nightwatch.models.nats_config import NatsConnectionConfig

LOGGER = logging.getLogger(__name__)

CONTROL_SUBJECT = "control.bot"
CONTROL_STREAM_NAME = "CONTROL"

_STREAM_MAX_MSGS = 10_000
_STREAM_MAX_AGE_SECONDS = 86_400


class ControlEventPublisher(NatsConnector):
    """Publisher for BotControlEvent data to the NATS JetStream control channel."""

    def __init__(self, config: NatsConnectionConfig | None = None, metrics: NightwatchMetrics | None = None) -> None:
        """Initialize the ControlEventPublisher with NATS connection parameters."""
        super().__init__(config=config, metrics=metrics)

    async def setup_stream(self) -> None:
        """Ensure the JetStream stream exists for the control subject.

        This method is idempotent — safe to call on every startup. If the
        stream already exists it is left unchanged; otherwise it is created
        with bounded retention (10 000 messages / 24-hour max age).
        """
        if not self.client.is_connected:
            LOGGER.warning("NATS publisher is not connected. Calling connect().")
            await self.connect()

        js = self.client.jetstream()
        stream_config = StreamConfig(
            name=CONTROL_STREAM_NAME,
            subjects=[CONTROL_SUBJECT],
            storage=StorageType.FILE,
            retention=RetentionPolicy.LIMITS,
            max_msgs=_STREAM_MAX_MSGS,
            max_age=_STREAM_MAX_AGE_SECONDS,
        )
        try:
            await js.stream_info(CONTROL_STREAM_NAME)
            LOGGER.info("JetStream stream '%s' already exists.", CONTROL_STREAM_NAME)
        except NotFoundError:
            await js.add_stream(config=stream_config)
            LOGGER.info("JetStream stream '%s' created.", CONTROL_STREAM_NAME)

    async def publish(self, event: BotControlEvent) -> None:
        """Publish a BotControlEvent to the control.bot subject via JetStream.

        Args:
            event: The BotControlEvent to publish.
        """
        if not self.client.is_connected:
            raise ConnectionError("ControlEventPublisher is not connected. Call connect() first.")

        js = self.client.jetstream()
        payload = event.model_dump_json().encode("utf-8")
        await js.publish(CONTROL_SUBJECT, payload)
        if self._metrics:
            self._metrics.control_events_published_total.inc()
        LOGGER.debug("Published control event to '%s'.", CONTROL_SUBJECT)
