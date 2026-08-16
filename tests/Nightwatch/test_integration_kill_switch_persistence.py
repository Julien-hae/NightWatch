# mypy: disable-error-code="import-untyped"
"""Integration test: kill-switch state survives an empty JetStream control backlog.

Reproduces the production readiness audit finding: JetStream's ``CONTROL``
stream is bounded (10k messages / 24h max age), so a kill command in effect
longer than that window can silently age out of the backlog a restart
drains. ``KillSwitch`` defaults to ``trading_enabled=True``, so an empty
backlog used to be indistinguishable from "never killed" — a restart would
silently resume trading regardless of the operator's last instruction.

This test drives the real ``Nightwatch.main._connect_nats`` orchestration
against a real, disposable Postgres and a real ``nats-server`` (JetStream),
kills trading, purges the control stream to simulate retention expiry, and
asserts that a second, independent boot restores the killed state from
Postgres instead of defaulting to trading enabled.
"""

from __future__ import annotations

import asyncio
import os
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Coroutine, TypeVar

from alembic import command
from nats.aio.client import Client as NatsClient
from sqlalchemy import create_engine, text

from Nightwatch.db.bootstrap import PersistenceContext, bootstrap_persistence
from Nightwatch.main import RunConfig, _connect_nats
from Nightwatch.messaging.control_event_publisher import CONTROL_STREAM_NAME, ControlEventPublisher
from Nightwatch.metrics.metrics import NightwatchMetrics
from Nightwatch.models.bot_control_event import BotControlEvent
from Nightwatch.models.nats_config import NatsConnectionConfig
from Nightwatch.pipeline.kill_switch import KillSwitch
from tests.fixtures.db import RESET_DB_SQL, alembic_cfg, to_pg_dsn
from tests.fixtures.nats_server import NatsServerFixture

_T = TypeVar("_T")


@unittest.skipUnless(
    os.environ.get("RUN_INTEGRATION") and os.environ.get("DATABASE_URL"),
    "Integration tests require RUN_INTEGRATION=1 and DATABASE_URL",
)
class TestKillSwitchSurvivesEmptyBacklog(unittest.TestCase):
    """A kill command must not be forgotten once JetStream's retention drops it."""

    database_url: str
    nats: NatsServerFixture
    loop: asyncio.AbstractEventLoop

    @classmethod
    def setUpClass(cls) -> None:
        raw_url = os.environ.get("DATABASE_URL")
        assert raw_url is not None
        cls.database_url = raw_url

        sync_url = to_pg_dsn(raw_url)
        engine = create_engine(sync_url)
        with engine.connect() as conn:
            conn.execute(text(RESET_DB_SQL))
            conn.commit()
        command.upgrade(alembic_cfg(sync_url), "head")
        engine.dispose()

        cls.nats = NatsServerFixture(jetstream=True)
        cls.nats.start()
        cls.loop = asyncio.new_event_loop()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.nats.stop()
        cls.loop.close()

    def _run(self, coro: Coroutine[Any, Any, _T]) -> _T:
        return self.loop.run_until_complete(coro)

    def _run_config(self) -> RunConfig:
        return RunConfig(
            symbol="BTC/USD",
            initial_cash=Decimal("10000"),
            order_notional=Decimal("100"),
            fee_rate=Decimal("0.001"),
            window_sec=10.0,
            threshold_pct=0.3,
            database_url=self.database_url,
            nats_servers=self.nats.url,
            http_host="127.0.0.1",
            http_port=8000,
        )

    async def _boot_and_connect(self, ctx: PersistenceContext, kill_switch: KillSwitch) -> tuple[Any, Any, Any]:
        """Run ``_connect_nats`` for one simulated process boot; return its connection bundle."""
        metrics = NightwatchMetrics()
        bundle = await _connect_nats(self._run_config(), kill_switch, metrics, ctx.kill_switch_state_repo)
        assert bundle is not None
        return bundle

    async def _close_bundle(self, bundle: tuple[Any, Any, Any]) -> None:
        nats_connector, control_sub, tick_publisher = bundle
        await control_sub.close()
        await tick_publisher.close()
        await nats_connector.close()

    async def _purge_control_stream(self) -> None:
        """Delete every message in the CONTROL stream, simulating its own retention expiring."""
        nc = NatsClient()
        await nc.connect(servers=[self.nats.url])
        try:
            js = nc.jetstream()
            await js.purge_stream(CONTROL_STREAM_NAME)
        finally:
            await nc.close()

    async def _publish_kill(self) -> None:
        publisher = ControlEventPublisher(config=NatsConnectionConfig(servers=[self.nats.url]))
        await publisher.connect()
        try:
            await publisher.setup_stream()
            await publisher.publish(BotControlEvent(kill=True, reason="audit regression test", timestamp=datetime.now(timezone.utc)))
        finally:
            await publisher.close()

    def test_kill_state_restored_from_postgres_after_backlog_expires(self) -> None:
        """Kill trading, purge the backlog (simulating retention expiry), then reboot."""

        # ── Boot #1: bootstrap, connect, then a real kill command arrives ──
        async def _boot_one() -> None:
            metrics = NightwatchMetrics()
            ctx = await bootstrap_persistence(self.database_url, metrics=metrics)
            kill_switch = KillSwitch(metrics=metrics, ready=False)
            try:
                bundle = await self._boot_and_connect(ctx, kill_switch)
                try:
                    self.assertTrue(kill_switch.trading_enabled)

                    await self._publish_kill()

                    deadline = asyncio.get_event_loop().time() + 5.0
                    while kill_switch.trading_enabled and asyncio.get_event_loop().time() < deadline:
                        await asyncio.sleep(0.05)
                    self.assertFalse(kill_switch.trading_enabled, "kill command should have been applied")

                    persisted = await ctx.kill_switch_state_repo.get()
                    assert persisted is not None
                    self.assertFalse(persisted.trading_enabled, "the applied kill event should have been mirrored to Postgres")
                finally:
                    await self._close_bundle(bundle)
            finally:
                await ctx.close()

        self._run(_boot_one())
        self._run(self._purge_control_stream())

        # ── Boot #2: fresh process, empty JetStream backlog ──
        async def _boot_two() -> bool:
            metrics = NightwatchMetrics()
            ctx = await bootstrap_persistence(self.database_url, metrics=metrics)
            kill_switch = KillSwitch(metrics=metrics, ready=False)
            try:
                bundle = await self._boot_and_connect(ctx, kill_switch)
                try:
                    return kill_switch.trading_enabled
                finally:
                    await self._close_bundle(bundle)
            finally:
                await ctx.close()

        trading_enabled_after_reboot = self._run(_boot_two())
        self.assertFalse(
            trading_enabled_after_reboot,
            "an empty JetStream backlog must fall back to the last Postgres-recorded state, not silently resume trading",
        )


if __name__ == "__main__":
    unittest.main()
