"""Defines the ControlEventSubscriber class for consuming BotControlEvent data from NATS JetStream."""

import logging
from typing import Any, Awaitable, Callable

from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy
from nats.js.client import JetStreamContext
from pydantic import ValidationError

from Nightwatch.metrics import NightwatchMetrics
from Nightwatch.models.bot_control_event import BotControlEvent
from Nightwatch.models.nats_config import NatsConnectionConfig
from Nightwatch.nats_connection import NatsConnector

LOGGER = logging.getLogger(__name__)

CONTROL_SUBJECT = "control.bot"
CONTROL_STREAM_NAME = "CONTROL"
DEFAULT_DURABLE_NAME = "trade-service"


class ControlEventSubscriber(NatsConnector):
    """Subscriber for BotControlEvent data from NATS JetStream using a durable consumer.

    Uses a push-based durable consumer so that unacknowledged messages are
    redelivered after the ack-wait timeout and messages survive subscriber
    restarts.
    """

    def __init__(self, config: NatsConnectionConfig | None = None, metrics: NightwatchMetrics | None = None) -> None:
        """Initialize the ControlEventSubscriber with NATS connection parameters."""
        super().__init__(config=config, metrics=metrics)
        self._subscription: JetStreamContext.PushSubscription | None = None

    async def subscribe(
        self,
        cb: Callable[[BotControlEvent], Awaitable[Any]] | None = None,
        *,
        durable: str = DEFAULT_DURABLE_NAME,
        ack_wait: float = 30.0,
    ) -> None:
        """Subscribe to control.bot with a durable JetStream consumer.

        Messages are acknowledged after successful processing. If a message
        cannot be parsed or the subscriber restarts before acking, JetStream
        will redeliver it after *ack_wait* seconds.

        Args:
            cb: Callback invoked with each successfully parsed BotControlEvent.
            durable: Name of the durable consumer (persists across restarts).
            ack_wait: Seconds JetStream waits before redelivering an unacked message.
        """
        if not self.client.is_connected:
            LOGGER.warning("NATS subscriber is not connected. Calling connect().")
            await self.connect()

        if self._subscription is not None:
            await self._subscription.unsubscribe()

        js = self.client.jetstream()

        consumer_config = ConsumerConfig(
            durable_name=durable,
            deliver_policy=DeliverPolicy.ALL,
            ack_policy=AckPolicy.EXPLICIT,
            ack_wait=ack_wait,
        )

        async def _handler(msg: Any) -> None:
            try:
                event = BotControlEvent.model_validate_json(msg.data)
            except ValidationError as exc:
                LOGGER.error("Error parsing control event message %s. exc=%s", msg, exc)
                await msg.nak()
                return
            if self._metrics:
                self._metrics.control_events_received_total.inc()
            if cb is not None:
                await cb(event)
            await msg.ack()

        self._subscription = await js.subscribe(
            subject=CONTROL_SUBJECT,
            stream=CONTROL_STREAM_NAME,
            config=consumer_config,
            cb=_handler,
            manual_ack=True,
        )
        await self.client.flush()
        LOGGER.debug("Subscribed to '%s' with durable consumer '%s'.", CONTROL_SUBJECT, durable)
