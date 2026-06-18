# mypy: disable-error-code="import-untyped"
"""Unit tests for ControlEventSubscriber — dead-letter advisory handler and message handler."""

import asyncio
import json
import logging
import unittest
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from prometheus_client import CollectorRegistry

from Nightwatch.messaging.control_event_subscriber import _MAX_DELIVER, ControlEventSubscriber
from Nightwatch.metrics.metrics import NightwatchMetrics
from Nightwatch.models.bot_control_event import BotControlEvent
from Nightwatch.models.nats_config import NatsConnectionConfig
from Nightwatch.pipeline.kill_switch import KillSwitch


def _counter_value(counter: Any) -> float:
    """Return the current value of a labelless Prometheus counter."""
    for mf in counter.collect():
        for sample in mf.samples:
            if sample.name.endswith("_total"):
                return float(sample.value)
    return 0.0


class TestControlEventSubscriber(unittest.TestCase):
    """Unit tests for ControlEventSubscriber dead-letter advisory and message handlers."""

    def setUp(self) -> None:
        registry = CollectorRegistry()
        self.metrics = NightwatchMetrics(registry=registry)
        self.subscriber = ControlEventSubscriber(
            config=NatsConnectionConfig(servers=["nats://localhost:4222"]),
            metrics=self.metrics,
        )

    def _run(self, coro: Any) -> Any:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def _build_mock_client(
        self,
        captured_advisory_cb: list[Any],
        captured_msg_cb: list[Any] | None = None,
    ) -> MagicMock:
        """Return a mocked NatsClient that captures advisory and message callbacks."""
        mock_client = MagicMock()
        mock_client.is_connected = True

        mock_push_sub = AsyncMock()
        mock_js = AsyncMock()

        async def _fake_js_subscribe(**kwargs: Any) -> AsyncMock:
            if captured_msg_cb is not None:
                captured_msg_cb.append(kwargs.get("cb"))
            return mock_push_sub

        mock_js.subscribe = _fake_js_subscribe
        mock_client.jetstream.return_value = mock_js

        async def _fake_nats_subscribe(_subject: str, cb: Any) -> AsyncMock:
            captured_advisory_cb.append(cb)
            return AsyncMock()

        mock_client.subscribe = _fake_nats_subscribe
        mock_client.flush = AsyncMock()
        return mock_client

    @staticmethod
    async def _noop_cb(_event: BotControlEvent) -> None:
        """Default no-op callback for tests that don't need to inspect received events."""

    def _subscribe_and_get_callbacks(
        self,
        cb: Any = None,
        durable: str = "test-consumer",
    ) -> tuple[Any, Any]:
        """Run subscribe() with a mocked client and return (advisory_handler, message_handler)."""
        advisory_cbs: list[Any] = []
        msg_cbs: list[Any] = []
        mock_client = self._build_mock_client(advisory_cbs, msg_cbs)
        self.subscriber._nc = mock_client
        self._run(self.subscriber.subscribe(cb if cb is not None else self._noop_cb, durable=durable))
        self.assertEqual(len(advisory_cbs), 1, "Expected exactly one advisory callback to be registered")
        self.assertEqual(len(msg_cbs), 1, "Expected exactly one message callback to be registered")
        return advisory_cbs[0], msg_cbs[0]

    @staticmethod
    def _make_msg(data: bytes) -> AsyncMock:
        msg = AsyncMock()
        msg.data = data
        return msg

    def test_advisory_logs_critical_and_increments_metric(self) -> None:
        """Advisory handler emits a CRITICAL log and increments control_events_dead_lettered_total."""
        advisory_cb, _ = self._subscribe_and_get_callbacks()

        payload = json.dumps({"stream_seq": 42, "deliveries": _MAX_DELIVER}).encode()
        before = _counter_value(self.metrics.control_events_dead_lettered_total)

        with self.assertLogs("Nightwatch.messaging.control_event_subscriber", level=logging.CRITICAL) as log_ctx:
            self._run(advisory_cb(self._make_msg(payload)))

        self.assertTrue(any("dead-lettered" in line for line in log_ctx.output))
        self.assertEqual(_counter_value(self.metrics.control_events_dead_lettered_total), before + 1)

    def test_advisory_logs_stream_seq_from_payload(self) -> None:
        """Advisory handler includes the stream_seq value from the advisory payload in the CRITICAL log."""
        advisory_cb, _ = self._subscribe_and_get_callbacks()

        payload = json.dumps({"stream_seq": 99, "deliveries": _MAX_DELIVER}).encode()

        with self.assertLogs("Nightwatch.messaging.control_event_subscriber", level=logging.CRITICAL) as log_ctx:
            self._run(advisory_cb(self._make_msg(payload)))

        self.assertTrue(any("99" in line for line in log_ctx.output))

    def test_advisory_handles_invalid_json_without_raising(self) -> None:
        """Advisory handler recovers from a corrupt advisory payload and still logs CRITICAL."""
        advisory_cb, _ = self._subscribe_and_get_callbacks()

        with self.assertLogs("Nightwatch.messaging.control_event_subscriber", level=logging.CRITICAL) as log_ctx:
            self._run(advisory_cb(self._make_msg(b"not-valid-json!!!")))

        self.assertTrue(any("dead-lettered" in line for line in log_ctx.output))
        self.assertEqual(_counter_value(self.metrics.control_events_dead_lettered_total), 1.0)

    def test_advisory_uses_unknown_default_for_missing_stream_seq(self) -> None:
        """Advisory handler falls back to 'unknown' for stream_seq when the field is absent in the payload."""
        advisory_cb, _ = self._subscribe_and_get_callbacks()

        with self.assertLogs("Nightwatch.messaging.control_event_subscriber", level=logging.CRITICAL) as log_ctx:
            self._run(advisory_cb(self._make_msg(json.dumps({}).encode())))

        self.assertTrue(any("unknown" in line for line in log_ctx.output))

    def test_advisory_without_metrics_does_not_raise(self) -> None:
        """Advisory handler fires correctly even when no NightwatchMetrics instance is provided."""
        subscriber_no_metrics = ControlEventSubscriber(
            config=NatsConnectionConfig(servers=["nats://localhost:4222"]),
            metrics=None,
        )
        advisory_cbs: list[Any] = []
        mock_client = self._build_mock_client(advisory_cbs)
        subscriber_no_metrics._nc = mock_client

        async def _noop(e: BotControlEvent) -> None:
            pass

        self._run(subscriber_no_metrics.subscribe(_noop, durable="no-metrics-consumer"))

        payload = json.dumps({"stream_seq": 7, "deliveries": _MAX_DELIVER}).encode()
        with self.assertLogs("Nightwatch.messaging.control_event_subscriber", level=logging.CRITICAL):
            self._run(advisory_cbs[0](self._make_msg(payload)))

    def test_advisory_increments_counter_on_each_dead_letter(self) -> None:
        """Each dead-letter advisory increments the counter independently."""
        advisory_cb, _ = self._subscribe_and_get_callbacks()

        payload = json.dumps({"stream_seq": 1, "deliveries": _MAX_DELIVER}).encode()

        with self.assertLogs("Nightwatch.messaging.control_event_subscriber", level=logging.CRITICAL):
            self._run(advisory_cb(self._make_msg(payload)))
        with self.assertLogs("Nightwatch.messaging.control_event_subscriber", level=logging.CRITICAL):
            self._run(advisory_cb(self._make_msg(payload)))

        self.assertEqual(_counter_value(self.metrics.control_events_dead_lettered_total), 2.0)

    def test_message_handler_terminates_poison_message(self) -> None:
        """Handler calls term() and increments parse_errors_total for an unparsable message."""
        _, msg_cb = self._subscribe_and_get_callbacks()

        mock_msg = self._make_msg(b"this is not valid json")
        before = _counter_value(self.metrics.parse_errors_total)

        self._run(msg_cb(mock_msg))

        mock_msg.term.assert_called_once()
        mock_msg.ack.assert_not_called()
        self.assertEqual(_counter_value(self.metrics.parse_errors_total), before + 1)

    def test_message_handler_acks_valid_event_and_calls_callback(self) -> None:
        """Handler acks a valid BotControlEvent, invokes the user callback, and increments received counter."""
        received: list[BotControlEvent] = []

        async def _cb(e: BotControlEvent) -> None:
            received.append(e)

        _, msg_cb = self._subscribe_and_get_callbacks(cb=_cb, durable="ack-test")

        event = BotControlEvent(kill=True, timestamp=datetime.now(timezone.utc), reason="unit test")
        mock_msg = self._make_msg(event.model_dump_json().encode())

        self._run(msg_cb(mock_msg))

        mock_msg.ack.assert_called_once()
        mock_msg.term.assert_not_called()
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].reason, "unit test")
        self.assertEqual(_counter_value(self.metrics.control_events_received_total), 1.0)

    def test_subscribe_without_callback_raises_value_error(self) -> None:
        """Calling subscribe() without a callback should raise a ValueError."""
        with self.assertRaises(ValueError):
            self._run(self.subscriber.subscribe(cb=None))  # type: ignore[arg-type]

    def test_drain_backlog_logs_restored_state(self) -> None:
        """Draining the backlog emits an info log with the restored kill-switch state."""
        event = BotControlEvent(kill=True, timestamp=datetime.now(timezone.utc), reason="backlog drain test")
        mock_msg = self._make_msg(event.model_dump_json().encode())
        mock_msg.ack = AsyncMock()
        mock_sub = AsyncMock()
        mock_sub.next_msg = AsyncMock(return_value=mock_msg)
        mock_sub.unsubscribe = AsyncMock()
        mock_js = AsyncMock()
        mock_js.subscribe = AsyncMock(return_value=mock_sub)
        mock_client = MagicMock()
        mock_client.is_connected = True
        mock_client.jetstream.return_value = mock_js

        self.subscriber._nc = mock_client
        kill_switch = KillSwitch()

        with self.assertLogs("Nightwatch.messaging.control_event_subscriber", level=logging.INFO) as log_ctx:
            self._run(self.subscriber.drain_backlog(kill_switch))

        self.assertTrue(any("Restored" in line and "trading_enabled=False" in line for line in log_ctx.output))
