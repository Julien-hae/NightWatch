"""Defines the ControlEventSubscriber class for consuming BotControlEvent data from NATS JetStream."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy
from nats.js.client import JetStreamContext
from pydantic import ValidationError

from Nightwatch.messaging.control_event_publisher import CONTROL_STREAM_NAME, CONTROL_SUBJECT
from Nightwatch.messaging.nats_connection import NatsConnector
from Nightwatch.metrics import NightwatchMetrics
from Nightwatch.models.bot_control_event import BotControlEvent
from Nightwatch.models.nats_config import NatsConnectionConfig

LOGGER = logging.getLogger(__name__)

DEFAULT_DURABLE_NAME = "trade-service"

# Maximum redelivery attempts for a single message before JetStream marks it as dead-lettered.
_MAX_DELIVER = 5


class ControlEventSubscriber(NatsConnector):
    """Subscriber for BotControlEvent data from NATS JetStream using a durable consumer.

    Uses a push-based durable consumer so that unacknowledged messages are
    redelivered after the ack-wait timeout and messages survive subscriber
    restarts. Unparse-able (poison) messages are terminated immediately so
    they do not churn redelivery.
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

        Messages are acknowledged after successful processing. Unparse-able
        (poison) messages are terminated immediately to prevent infinite
        redelivery. If the subscriber restarts before a valid message is
        acked, JetStream redelivers it after *ack_wait* seconds (up to
        *_MAX_DELIVER* attempts total).

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
            deliver_policy=DeliverPolicy.NEW,
            ack_policy=AckPolicy.EXPLICIT,
            ack_wait=ack_wait,
            max_deliver=_MAX_DELIVER,
        )

        async def _handler(msg: Any) -> None:
            try:
                event = BotControlEvent.model_validate_json(msg.data)
            except ValidationError as exc:
                if self._metrics is not None:
                    self._metrics.parse_errors_total.inc()
                LOGGER.error("Error parsing control event message %s. exc=%s", msg, exc)
                await msg.term()
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
