"""Integration tests for Alembic migrations.

Requires both ``RUN_INTEGRATION=1`` and a reachable Postgres pointed to by
``DATABASE_URL`` (e.g. the ``trade-db`` service in ``docker-compose.yml``).

Tests:
- Run migrations on an empty DB → all expected tables exist.
- Insert two orders with the same ``idempotency_key`` → second insert fails.
"""

import os
import unittest
import uuid
from datetime import datetime, timezone

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError


def _alembic_cfg(database_url: str) -> Config:
    """Return an Alembic Config pointing at *database_url*."""
    ini_path = os.path.join(os.path.dirname(__file__), "..", "..", "alembic.ini")
    cfg = Config(os.path.abspath(ini_path))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def _sync_url(url: str) -> str:
    """Strip ``+asyncpg`` so SQLAlchemy uses the psycopg2/pg8000 driver."""
    for prefix, replacement in (
        ("postgresql+asyncpg://", "postgresql://"),
        ("postgres+asyncpg://", "postgresql://"),
    ):
        if url.startswith(prefix):
            return replacement + url[len(prefix) :]
    return url


@unittest.skipUnless(os.environ.get("RUN_INTEGRATION"), "Integration tests require RUN_INTEGRATION=1")
class TestMigrations(unittest.TestCase):
    """Verify Alembic migrations against a live Postgres database."""

    def setUp(self) -> None:
        raw_url = os.environ.get("DATABASE_URL")
        if not raw_url:
            self.skipTest("DATABASE_URL is not set; cannot run migration integration tests")

        self.sync_url = _sync_url(raw_url)
        self.engine = create_engine(self.sync_url)
        self.cfg = _alembic_cfg(self.sync_url)

        # Start each test on a clean schema.
        with self.engine.connect() as conn:
            conn.execute(text("DROP TABLE IF EXISTS fills, orders, signals, positions, equity_snapshots, alembic_version CASCADE"))
            conn.commit()

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_upgrade_creates_all_tables(self) -> None:
        command.upgrade(self.cfg, "head")

        expected_tables = {"signals", "orders", "fills", "positions", "equity_snapshots"}
        with self.engine.connect() as conn:
            rows = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")).fetchall()
        actual_tables = {row[0] for row in rows}

        self.assertTrue(expected_tables.issubset(actual_tables), f"Missing tables: {expected_tables - actual_tables}")

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

        for table in ("signals", "orders", "fills", "positions", "equity_snapshots"):
            self.assertNotIn(table, actual_tables)
