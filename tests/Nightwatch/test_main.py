"""Tests for graceful shutdown wiring in main.py (SIGINT/SIGTERM handling, drain, close)."""

import asyncio
import signal
import unittest
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable
from unittest.mock import AsyncMock, MagicMock, patch

from Nightwatch.db.repositories import InMemoryKillSwitchStateRepo
from Nightwatch.main import _ingest_ticks, _install_signal_handlers, _restore_kill_switch_from_postgres, _shutdown_resources
from Nightwatch.models.service_health import ServiceHealth
from Nightwatch.pipeline.kill_switch import KillSwitch
from tests.fixtures.tick_factory import make_tick


class TestInstallSignalHandlers(unittest.TestCase):
    """SIGINT/SIGTERM must flip the stop event and request server exit."""

    def test_signal_triggers_stop_event_and_server_exit(self) -> None:
        """Invoking the registered handler sets stop_event and server.should_exit."""

        async def scenario() -> None:
            stop_event = asyncio.Event()
            server = MagicMock()
            server.should_exit = False
            loop = asyncio.get_running_loop()
            captured: dict[signal.Signals, Callable[[], None]] = {}

            def fake_add_signal_handler(sig: signal.Signals, callback: Callable[..., None], *args: Any) -> None:
                captured[sig] = lambda: callback(*args)

            with patch.object(loop, "add_signal_handler", side_effect=fake_add_signal_handler):
                _install_signal_handlers(stop_event, server)

            self.assertIn(signal.SIGINT, captured)
            self.assertIn(signal.SIGTERM, captured)
            self.assertFalse(stop_event.is_set())

            captured[signal.SIGTERM]()

            self.assertTrue(stop_event.is_set())
            self.assertTrue(server.should_exit)

        asyncio.run(scenario())


class TestIngestTicksGracefulStop(unittest.TestCase):
    """The ingest loop must finish an in-flight tick before honoring a stop request."""

    def _make_kraken(self, ticks: list[Any]) -> MagicMock:
        async def stream_ticks() -> AsyncIterator[Any]:
            for tick in ticks:
                yield tick

        kraken = MagicMock()
        kraken.stream_ticks.return_value = stream_ticks()
        return kraken

    def test_stops_after_finishing_in_flight_tick(self) -> None:
        """A stop_event set mid-processing still lets the current tick finish, then breaks."""
        ticks = [make_tick(), make_tick(), make_tick()]
        kraken = self._make_kraken(ticks)
        health = ServiceHealth()
        stop_event = asyncio.Event()

        runner = MagicMock()

        async def on_tick(_tick: Any) -> None:
            # Simulate a SIGTERM arriving while this tick's DB write is in flight.
            stop_event.set()

        runner.on_market_tick_async = AsyncMock(side_effect=on_tick)

        asyncio.run(_ingest_ticks(kraken, runner, health, None, stop_event))

        self.assertEqual(runner.on_market_tick_async.await_count, 1)
        self.assertTrue(health.ws_connected)

    def test_processes_all_ticks_when_never_stopped(self) -> None:
        """With no stop request, every tick from the stream is processed."""
        ticks = [make_tick(), make_tick(), make_tick()]
        kraken = self._make_kraken(ticks)
        health = ServiceHealth()
        stop_event = asyncio.Event()

        runner = MagicMock()
        runner.on_market_tick_async = AsyncMock(return_value=None)

        asyncio.run(_ingest_ticks(kraken, runner, health, None, stop_event))

        self.assertEqual(runner.on_market_tick_async.await_count, len(ticks))

    def test_publishes_before_processing_and_survives_publish_failure(self) -> None:
        """A tick_publisher failure is swallowed and never blocks pipeline processing."""
        ticks = [make_tick()]
        kraken = self._make_kraken(ticks)
        health = ServiceHealth()
        stop_event = asyncio.Event()

        runner = MagicMock()
        runner.on_market_tick_async = AsyncMock(return_value=None)
        tick_publisher = MagicMock()
        tick_publisher.publish = AsyncMock(side_effect=RuntimeError("nats down"))

        asyncio.run(_ingest_ticks(kraken, runner, health, tick_publisher, stop_event))

        tick_publisher.publish.assert_awaited_once()
        runner.on_market_tick_async.assert_awaited_once()


class TestShutdownResources(unittest.TestCase):
    """The shutdown helper must drain NATS and close the Kraken/DB connections, best-effort."""

    def _make_mocks(self) -> dict[str, Any]:
        control_sub = MagicMock()
        control_sub.close = AsyncMock()
        tick_publisher = MagicMock()
        tick_publisher.close = AsyncMock()
        nats_connector = MagicMock()
        nats_connector.client.is_connected = True
        nats_connector.close = AsyncMock()
        kraken = MagicMock()
        kraken.close = AsyncMock()
        persistence = MagicMock()
        persistence.close = AsyncMock()
        return {
            "control_sub": control_sub,
            "tick_publisher": tick_publisher,
            "nats_connector": nats_connector,
            "kraken": kraken,
            "persistence": persistence,
        }

    def test_closes_every_resource(self) -> None:
        """All five components are closed/drained exactly once."""
        mocks = self._make_mocks()

        asyncio.run(_shutdown_resources(**mocks))

        mocks["control_sub"].close.assert_awaited_once()
        mocks["tick_publisher"].close.assert_awaited_once()
        mocks["nats_connector"].close.assert_awaited_once()
        mocks["kraken"].close.assert_awaited_once()
        mocks["persistence"].close.assert_awaited_once()

    def test_skips_nats_close_when_already_disconnected(self) -> None:
        """A NATS connector reporting is_connected=False is not closed again."""
        mocks = self._make_mocks()
        mocks["nats_connector"].client.is_connected = False

        asyncio.run(_shutdown_resources(**mocks))

        mocks["nats_connector"].close.assert_not_awaited()
        mocks["kraken"].close.assert_awaited_once()
        mocks["persistence"].close.assert_awaited_once()

    def test_tolerates_none_when_nats_disabled(self) -> None:
        """When NATS_SERVERS is unset, control_sub/tick_publisher/nats_connector are None."""
        mocks = self._make_mocks()
        mocks["control_sub"] = None
        mocks["tick_publisher"] = None
        mocks["nats_connector"] = None

        asyncio.run(_shutdown_resources(**mocks))

        mocks["kraken"].close.assert_awaited_once()
        mocks["persistence"].close.assert_awaited_once()

    def test_a_failing_close_does_not_block_the_rest(self) -> None:
        """One component's close() raising must not prevent the others from closing."""
        mocks = self._make_mocks()
        mocks["control_sub"].close = AsyncMock(side_effect=RuntimeError("drain failed"))

        asyncio.run(_shutdown_resources(**mocks))

        mocks["control_sub"].close.assert_awaited_once()
        mocks["tick_publisher"].close.assert_awaited_once()
        mocks["nats_connector"].close.assert_awaited_once()
        mocks["kraken"].close.assert_awaited_once()
        mocks["persistence"].close.assert_awaited_once()

    def test_closes_in_order_nats_then_kraken_then_db(self) -> None:
        """NATS is drained, then Kraken, then the DB pool — never DB before NATS."""
        mocks = self._make_mocks()
        order: list[str] = []
        mocks["control_sub"].close = AsyncMock(side_effect=lambda: order.append("control_sub"))
        mocks["tick_publisher"].close = AsyncMock(side_effect=lambda: order.append("tick_publisher"))
        mocks["nats_connector"].close = AsyncMock(side_effect=lambda: order.append("nats_connector"))
        mocks["kraken"].close = AsyncMock(side_effect=lambda: order.append("kraken"))
        mocks["persistence"].close = AsyncMock(side_effect=lambda: order.append("persistence"))

        asyncio.run(_shutdown_resources(**mocks))

        self.assertEqual(
            order,
            ["control_sub", "tick_publisher", "nats_connector", "kraken", "persistence"],
        )


class TestRestoreKillSwitchFromPostgres(unittest.TestCase):
    """The Postgres fallback used when the JetStream control backlog is empty."""

    def test_falls_back_to_persisted_killed_state(self) -> None:
        """A persisted trading_enabled=False must be applied when the backlog was empty."""

        async def scenario() -> None:
            repo = InMemoryKillSwitchStateRepo()
            await repo.save(trading_enabled=False, reason="paused for the weekend", updated_at=datetime.now(timezone.utc))

            kill_switch = KillSwitch()
            self.assertTrue(kill_switch.trading_enabled)  # starting from the class default

            await _restore_kill_switch_from_postgres(kill_switch, repo)

            self.assertFalse(kill_switch.trading_enabled, "an empty JetStream backlog must not override a persisted kill")

        asyncio.run(scenario())

    def test_no_persisted_state_leaves_default_enabled(self) -> None:
        """A brand-new deployment with nothing in Postgres yet keeps trading enabled."""

        async def scenario() -> None:
            repo = InMemoryKillSwitchStateRepo()
            kill_switch = KillSwitch()

            await _restore_kill_switch_from_postgres(kill_switch, repo)

            self.assertTrue(kill_switch.trading_enabled)

        asyncio.run(scenario())

    def test_falls_back_to_persisted_enabled_state(self) -> None:
        """A persisted trading_enabled=True is applied too, not just kills."""

        async def scenario() -> None:
            repo = InMemoryKillSwitchStateRepo()
            await repo.save(trading_enabled=True, reason="resumed", updated_at=datetime.now(timezone.utc))

            kill_switch = KillSwitch()
            await _restore_kill_switch_from_postgres(kill_switch, repo)

            self.assertTrue(kill_switch.trading_enabled)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
