"""Defines the ControlEventSubscriber class for consuming BotControlEvent data from NATS JetStream."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Awaitable, Callable

from nats.aio.subscription import Subscription
from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy
from nats.js.client import JetStreamContext
from pydantic import ValidationError

from Nightwatch.messaging.control_event_publisher import CONTROL_STREAM_NAME, CONTROL_SUBJECT
from Nightwatch.messaging.nats_connection import NatsConnector
from Nightwatch.metrics.metrics import NightwatchMetrics
from Nightwatch.models.bot_control_event import BotControlEvent
from Nightwatch.models.nats_config import NatsConnectionConfig
from Nightwatch.pipeline.kill_switch import KillSwitch

LOGGER = logging.getLogger(__name__)

DEFAULT_DURABLE_NAME = "trade-service"
_DEFAULT_DELIVER_POLICY = DeliverPolicy.LAST
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
        self._advisory_sub: Subscription | None = None
        self._uid = uuid.uuid4()

    async def subscribe(
        self,
        cb: Callable[[BotControlEvent], Awaitable[Any]],
        *,
        durable: str = DEFAULT_DURABLE_NAME,
        ack_wait: float = 30.0,
        deliver_policy: DeliverPolicy = _DEFAULT_DELIVER_POLICY,
    ) -> None:
        """Subscribe to control.bot with a durable JetStream consumer.

        Messages are acknowledged after successful processing. Unparse-able
        (poison) messages are terminated immediately to prevent infinite
        redelivery. If the subscriber restarts before a valid message is
        acked, JetStream redelivers it after *ack_wait* seconds (up to
        *_MAX_DELIVER* attempts total).

        Args:
            cb: Callback invoked with each successfully parsed BotControlEvent.
                The callback must complete any durable state changes before it
                returns because ACK is sent only after ``cb`` succeeds.
            durable: Name of the durable consumer (persists across restarts).
            ack_wait: Seconds JetStream waits before redelivering an unacked message.
            deliver_policy: JetStream delivery policy for the durable consumer.
                Defaults to _DEFAULT_DELIVER_POLICY so a restarted subscriber recovers
                the most recent state without replaying the full history.
        """
        if cb is None:
            raise ValueError("Callback function must be provided for subscription.")
        if not self.client.is_connected:
            LOGGER.warning("NATS subscriber is not connected. Calling connect().")
            await self.connect()

        if self._subscription is not None:
            await self._subscription.unsubscribe()

        js = self.client.jetstream()

        consumer_config = ConsumerConfig(
            durable_name=durable,
            deliver_policy=deliver_policy,
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
            await cb(event)
            await msg.ack()

        self._subscription = await js.subscribe(
            subject=CONTROL_SUBJECT,
            stream=CONTROL_STREAM_NAME,
            config=consumer_config,
            cb=_handler,
            manual_ack=True,
        )

        if self._advisory_sub is not None:
            await self._advisory_sub.unsubscribe()

        advisory_subject = f"$JS.EVENT.ADVISORY.CONSUMER.MAX_DELIVERIES.{CONTROL_STREAM_NAME}.{durable}"

        async def _advisory_handler(msg: Any) -> None:
            try:
                parsed_data: Any = json.loads(msg.data)
            except (json.JSONDecodeError, UnicodeDecodeError):
                data: dict[str, Any] = {}
            else:
                data = parsed_data if isinstance(parsed_data, dict) else {}
            stream_seq = data.get("stream_seq", "unknown")
            deliveries = data.get("deliveries", _MAX_DELIVER)
            LOGGER.critical(
                "BotControlEvent dead-lettered after %s delivery attempts "
                "(stream=%s, consumer=%s, stream_seq=%s). "
                "A kill command may not have been processed — manual intervention required.",
                deliveries,
                CONTROL_STREAM_NAME,
                durable,
                stream_seq,
            )
            if self._metrics is not None:
                self._metrics.control_events_dead_lettered_total.inc()

        self._advisory_sub = await self.client.subscribe(advisory_subject, cb=_advisory_handler)

        await self.client.flush()
        LOGGER.debug("Subscribed to '%s' with durable consumer '%s'.", CONTROL_SUBJECT, durable)
        LOGGER.debug("Watching dead-letter advisory on '%s'.", advisory_subject)

    async def drain_backlog(self, kill_switch: KillSwitch, *, timeout: float = 5.0) -> int:
        """Fetch and apply the most recent control event from JetStream before normal processing.

        Uses an ephemeral consumer with ``DeliverPolicy.LAST`` so only the
        latest event is retrieved.  After draining, the *kill_switch* is
        marked ready so that the ``StrategyRunner`` can begin emitting
        signals.  If no messages are pending the switch is still marked ready.

        This method should be called **once at startup**, before any market
        ticks are processed, to close the safety gap where a kill command
        sent before a crash could be lost.

        Args:
            kill_switch: The ``KillSwitch`` instance to restore.
            timeout: Seconds to wait for a pending message before giving up.

        Returns:
            The number of events applied (0 or 1).
        """
        LOGGER.info("Draining JetStream backlog for control events with timeout %.1f seconds...", timeout)
        if not self.client.is_connected:
            LOGGER.warning("NATS subscriber is not connected. Calling connect().")
            await self.connect()

        js = self.client.jetstream()
        drain_consumer_name = f"drain-consumer-{self._uid}"

        sub = await js.subscribe(
            durable=drain_consumer_name,
            subject=CONTROL_SUBJECT,
            stream=CONTROL_STREAM_NAME,
            config=ConsumerConfig(
                deliver_policy=_DEFAULT_DELIVER_POLICY,
                ack_policy=AckPolicy.EXPLICIT,
            ),
        )
        LOGGER.info("Subscribed to JetStream with ephemeral consumer to drain backlog: %s", sub)

        applied = 0
        try:
            msg = await sub.next_msg(timeout=timeout)
            try:
                event = BotControlEvent.model_validate_json(msg.data)
                kill_switch.apply(event)
                await msg.ack()
                applied = 1
                LOGGER.info("Restored kill-switch state from backlog: trading_enabled=%s", kill_switch.trading_enabled)
            except ValidationError as exc:
                LOGGER.error("Failed to parse control event during backlog drain: %s", exc)
                await msg.term()
        except TimeoutError:
            LOGGER.info("No pending control events in JetStream backlog.")
        finally:
            await sub.unsubscribe()
            try:
                await js.delete_consumer(CONTROL_STREAM_NAME, drain_consumer_name)
                LOGGER.debug("Deleted ephemeral drain consumer '%s'.", drain_consumer_name)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Could not delete drain consumer '%s': %s", drain_consumer_name, exc)

        kill_switch.mark_ready()
        LOGGER.info("Backlog drain complete: %d event(s) applied, kill switch ready.", applied)
        return applied

    async def close(self) -> None:
        """Unsubscribe advisory and JetStream subscriptions before closing the connection.

        Cleans up both the dead-letter advisory core-NATS subscription and the
        durable JetStream push subscription so that no callbacks fire after the
        connection is drained.
        """
        if self._advisory_sub is not None:
            await self._advisory_sub.unsubscribe()
            self._advisory_sub = None
        if self._subscription is not None:
            await self._subscription.unsubscribe()
            self._subscription = None
        await super().close()
