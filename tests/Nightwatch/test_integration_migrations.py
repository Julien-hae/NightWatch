"""Integration tests for Alembic migrations.

Requires both ``RUN_INTEGRATION=1`` and a reachable Postgres pointed to by
``DATABASE_URL`` (e.g. the ``trade-db`` service in ``docker-compose.yml``).

Tests:
- Run migrations on an empty DB → all expected tables exist.
- Insert two orders with the same ``idempotency_key`` → second insert fails.
- Two ``portfolio_state`` rows are rejected by the singleton CHECK.
"""

import os
import unittest
import uuid
from datetime import datetime, timezone

from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from tests.fixtures.db import RESET_DB_SQL, alembic_cfg, to_pg_dsn


@unittest.skipUnless(os.environ.get("RUN_INTEGRATION"), "Integration tests require RUN_INTEGRATION=1")
class TestMigrations(unittest.TestCase):
    """Verify Alembic migrations against a live Postgres database."""

    def setUp(self) -> None:
        raw_url = os.environ.get("DATABASE_URL")
        if not raw_url:
            self.skipTest("DATABASE_URL is not set; cannot run migration integration tests")

        self.sync_url = to_pg_dsn(raw_url)
        self.engine = create_engine(self.sync_url)
        self.cfg = alembic_cfg(self.sync_url)

        # Start each test on a clean schema.
        with self.engine.connect() as conn:
            conn.execute(text(RESET_DB_SQL))
            conn.commit()

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_upgrade_creates_all_tables(self) -> None:
        command.upgrade(self.cfg, "head")

        expected_tables = {
            "signals",
            "orders",
            "fills",
            "positions",
            "equity_snapshots",
            "portfolio_state",
            "processing_cursor",
        }
        with self.engine.connect() as conn:
            rows = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")).fetchall()
        actual_tables = {row[0] for row in rows}

        self.assertTrue(expected_tables.issubset(actual_tables), f"Missing tables: {expected_tables - actual_tables}")

    def test_portfolio_state_rejects_second_row(self) -> None:
        command.upgrade(self.cfg, "head")

        with self.engine.connect() as conn:
            conn.execute(text("INSERT INTO portfolio_state (id, cash, updated_at) VALUES (1, 100, NOW())"))
            conn.commit()
            with self.assertRaises(IntegrityError):
                conn.execute(text("INSERT INTO portfolio_state (id, cash, updated_at) VALUES (2, 200, NOW())"))
                conn.commit()

    def test_duplicate_idempotency_key_raises(self) -> None:
        command.upgrade(self.cfg, "head")

        idempotency_key = uuid.uuid4()
        now = datetime.now(tz=timezone.utc)
        insert_sql = text(
            "INSERT INTO orders (order_id, idempotency_key, signal_id, symbol, side, qty, status, created_at) "
            "VALUES (:order_id, :idem_key, :signal_id, :symbol, :side, :qty, :status, :created_at)"
        )
        params_base = {
            "signal_id": str(uuid.uuid4()),
            "symbol": "BTC/USD",
            "side": "BUY",
            "qty": "0.01",
            "status": "NEW",
            "created_at": now,
            "idem_key": str(idempotency_key),
        }

        with self.engine.connect() as conn:
            # First insert must succeed.
            conn.execute(insert_sql, {**params_base, "order_id": str(uuid.uuid4())})
            conn.commit()

            # Second insert with the same idempotency_key must fail.
            with self.assertRaises(IntegrityError):
                conn.execute(insert_sql, {**params_base, "order_id": str(uuid.uuid4())})
                conn.commit()

    def test_downgrade_removes_all_tables(self) -> None:
        command.upgrade(self.cfg, "head")
        command.downgrade(self.cfg, "base")

        with self.engine.connect() as conn:
            rows = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")).fetchall()
        actual_tables = {row[0] for row in rows}

        for table in ("signals", "orders", "fills", "positions", "equity_snapshots", "portfolio_state", "processing_cursor"):
            self.assertNotIn(table, actual_tables)
