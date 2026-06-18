# mypy: disable-error-code="import-untyped"
"""Integration tests for JetStream ACK-after-commit safety with Postgres idempotency."""

from __future__ import annotations

import asyncio
import os
import unittest
import uuid
from collections.abc import Coroutine
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, TypeVar

import asyncpg  # type: ignore[import-untyped]
from alembic import command
from nats.aio.client import Client as NatsClient
from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy, RetentionPolicy, StorageType, StreamConfig
from sqlalchemy import create_engine, text

from Nightwatch.models.fill import Fill
from Nightwatch.models.order import Order, Status
from Nightwatch.models.signal import Side
from Nightwatch.pg_repositories import PgAtomicTradeWriter
from Nightwatch.repositories import OrderCreateResult
from tests.fixtures.db import RESET_DB_SQL, alembic_cfg, to_pg_dsn
from tests.fixtures.nats_server import NatsServerFixture

_T = TypeVar("_T")

_ORDER_STREAM = "ORDER_REQ"
_ORDER_SUBJECT = "order.request"
_MIN_REDELIVERY_COUNT = 2


def _make_order(signal_id: uuid.UUID) -> Order:
    return Order(
        order_id=uuid.uuid4(),
        signal_id=signal_id,
        side=Side.BUY,
        symbol="BTC/USD",
        qty=Decimal("0.002"),
        status=Status.NEW,
        created_at=datetime.now(timezone.utc),
    )


def _make_fill(order: Order) -> Fill:
    return Fill(
        fill_id=uuid.uuid4(),
        order_id=order.order_id,
        side=order.side,
        symbol=order.symbol,
        qty=order.qty,
        price=Decimal("50000"),
        fee=Decimal("0.10"),
        ts=datetime.now(timezone.utc),
    )


@unittest.skipUnless(
    os.environ.get("RUN_INTEGRATION") and os.environ.get("DATABASE_URL"),
    "Integration tests require RUN_INTEGRATION=1 and DATABASE_URL",
)
class TestJetStreamTransactionalAck(unittest.TestCase):
    """Verify crash windows around commit/ack do not produce partial or duplicate writes."""

    nats: NatsServerFixture
    loop: asyncio.AbstractEventLoop
    pool: asyncpg.Pool
    asyncpg_url: str

    @classmethod
    def setUpClass(cls) -> None:
        raw_url = os.environ.get("DATABASE_URL")
        if not raw_url:
            raise unittest.SkipTest("DATABASE_URL is not set")

        sync_url = to_pg_dsn(raw_url)
        engine = create_engine(sync_url)
        with engine.connect() as conn:
            conn.execute(text(RESET_DB_SQL))
            conn.commit()
        command.upgrade(alembic_cfg(sync_url), "head")
        engine.dispose()

        cls.asyncpg_url = to_pg_dsn(raw_url)
        cls.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(cls.loop)
        cls.pool = cls.loop.run_until_complete(asyncpg.create_pool(cls.asyncpg_url, min_size=1, max_size=3))

        cls.nats = NatsServerFixture(jetstream=True)
        cls.nats.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.loop.run_until_complete(cls.pool.close())
        cls.loop.close()
        cls.nats.stop()

    def _run(self, coro: Coroutine[Any, Any, _T]) -> _T:
        return self.loop.run_until_complete(coro)

    def setUp(self) -> None:
        async def _prepare() -> None:
            async with self.pool.acquire() as conn:
                await conn.execute("DELETE FROM fills")
                await conn.execute("DELETE FROM orders")
                await conn.execute("DELETE FROM positions")
                await conn.execute("DELETE FROM equity_snapshots")
                await conn.execute("DELETE FROM portfolio_state")
                await conn.execute("DELETE FROM processing_cursor")
            nc = await asyncpg_nats_connect(self.nats.url)
            js = nc.jetstream()
            try:
                await js.delete_stream(_ORDER_STREAM)
            except Exception:  # noqa: BLE001
                pass
            await js.add_stream(
                config=StreamConfig(
                    name=_ORDER_STREAM,
                    subjects=[_ORDER_SUBJECT],
                    storage=StorageType.FILE,
                    retention=RetentionPolicy.LIMITS,
                )
            )
            await nc.drain()

        self._run(_prepare())

    def test_failure_before_commit_redelivers_and_keeps_db_unchanged(self) -> None:
        """If processing fails before commit, message redelivers and DB remains unchanged."""

        async def _test() -> None:
            nc = await asyncpg_nats_connect(self.nats.url)
            js = nc.jetstream()

            sub = await js.subscribe(
                subject=_ORDER_SUBJECT,
                stream=_ORDER_STREAM,
                config=ConsumerConfig(
                    durable_name="tx-fail-before-commit",
                    deliver_policy=DeliverPolicy.NEW,
                    ack_policy=AckPolicy.EXPLICIT,
                    ack_wait=1.0,
                    max_deliver=5,
                ),
                manual_ack=True,
            )

            signal_id = uuid.uuid4()
            order = _make_order(signal_id)
            await js.publish(_ORDER_SUBJECT, order.model_dump_json().encode("utf-8"))

            deliveries = 0
            got_redelivery = asyncio.Event()

            deadline = asyncio.get_running_loop().time() + 10.0
            while asyncio.get_running_loop().time() < deadline and not got_redelivery.is_set():
                msg = await asyncio.wait_for(sub.next_msg(timeout=2.0), timeout=3.0)
                deliveries += 1
                if deliveries == 1:
                    async with self.pool.acquire() as conn:
                        try:
                            async with conn.transaction():
                                await conn.execute(
                                    """
                                    INSERT INTO orders (order_id, idempotency_key, signal_id, symbol, side, qty, status, created_at)
                                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                                    """,
                                    order.order_id,
                                    order.signal_id,
                                    order.signal_id,
                                    order.symbol,
                                    order.side.value,
                                    order.qty,
                                    order.status.value,
                                    order.created_at,
                                )
                                raise RuntimeError("crash before commit")
                        except RuntimeError:
                            pass
                else:
                    got_redelivery.set()
                    await msg.ack()

            async with self.pool.acquire() as conn:
                order_count = int(await conn.fetchval("SELECT COUNT(*) FROM orders"))
                fill_count = int(await conn.fetchval("SELECT COUNT(*) FROM fills"))

            await sub.unsubscribe()
            await nc.drain()

            self.assertTrue(got_redelivery.is_set(), "Expected redelivery after unacked failed transaction")
            self.assertGreaterEqual(deliveries, _MIN_REDELIVERY_COUNT)
            self.assertEqual(order_count, 0)
            self.assertEqual(fill_count, 0)

        self._run(_test())

    def test_redelivery_after_commit_keeps_single_order(self) -> None:
        """If crash happens after commit but before ACK, redelivery does not duplicate DB state."""

        async def _test() -> None:
            writer = PgAtomicTradeWriter(self.pool)
            nc = await asyncpg_nats_connect(self.nats.url)
            js = nc.jetstream()

            sub = await js.subscribe(
                subject=_ORDER_SUBJECT,
                stream=_ORDER_STREAM,
                config=ConsumerConfig(
                    durable_name="tx-redelivery-after-commit",
                    deliver_policy=DeliverPolicy.NEW,
                    ack_policy=AckPolicy.EXPLICIT,
                    ack_wait=1.0,
                    max_deliver=5,
                ),
                manual_ack=True,
            )

            signal_id = uuid.uuid4()
            order = _make_order(signal_id)
            fill = _make_fill(order)
            await js.publish(_ORDER_SUBJECT, order.model_dump_json().encode("utf-8"))

            deliveries = 0
            second_result: OrderCreateResult | None = None

            deadline = asyncio.get_running_loop().time() + 10.0
            while asyncio.get_running_loop().time() < deadline and deliveries < _MIN_REDELIVERY_COUNT:
                msg = await asyncio.wait_for(sub.next_msg(timeout=2.0), timeout=3.0)
                deliveries += 1

                result = await writer.write_trade(
                    order,
                    fill,
                    position_qty=order.qty,
                    cash=Decimal("9900.00"),
                    equity=Decimal("10000.00"),
                )

                if deliveries == 1:
                    self.assertEqual(result, OrderCreateResult.CREATED)
                    # Simulate crash window: committed, but ACK never sent.
                    continue

                second_result = result
                await msg.ack()

            async with self.pool.acquire() as conn:
                order_count = int(await conn.fetchval("SELECT COUNT(*) FROM orders WHERE signal_id = $1", signal_id))
                fill_count = int(await conn.fetchval("SELECT COUNT(*) FROM fills WHERE order_id = $1", order.order_id))

            await sub.unsubscribe()
            await nc.drain()

            self.assertGreaterEqual(deliveries, _MIN_REDELIVERY_COUNT)
            self.assertEqual(second_result, OrderCreateResult.ALREADY_EXISTS)
            self.assertEqual(order_count, 1)
            self.assertEqual(fill_count, 1)

        self._run(_test())


async def asyncpg_nats_connect(url: str) -> NatsClient:
    """Connect and return a NATS client for integration tests."""
    client = NatsClient()
    await client.connect(servers=[url], token=os.getenv("NATS_TOKEN", ""))
    return client
