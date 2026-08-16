# mypy: disable-error-code="import-untyped"
"""Integration test: a second trade-service instance must refuse to start.

Reproduces the production readiness audit finding: Signal.uid/Order.signal_id
are generated per-process (uuid4(), not derived from the tick itself), so the
existing idempotency (in-memory dedup + ON CONFLICT on signal_id) does not
catch two independent processes reacting to the same market data — each would
create its own, non-conflicting orders, silently doubling every trade. This
test drives the real bootstrap_persistence() against a real, disposable
Postgres and proves a second concurrent boot is rejected loudly, then that a
third boot succeeds once the first instance has released the lock.
"""

from __future__ import annotations

import asyncio
import os
import unittest
from typing import Any, Coroutine, TypeVar

from alembic import command
from sqlalchemy import create_engine, text

from Nightwatch.db.bootstrap import SingletonLockError, bootstrap_persistence
from tests.fixtures.db import RESET_DB_SQL, alembic_cfg, to_pg_dsn

_T = TypeVar("_T")


@unittest.skipUnless(
    os.environ.get("RUN_INTEGRATION") and os.environ.get("DATABASE_URL"),
    "Integration tests require RUN_INTEGRATION=1 and DATABASE_URL",
)
class TestSingletonLock(unittest.TestCase):
    """Only one bootstrap_persistence() context may be alive per database at a time."""

    database_url: str
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

        cls.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(cls.loop)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.loop.close()

    def _run(self, coro: Coroutine[Any, Any, _T]) -> _T:
        return self.loop.run_until_complete(coro)

    def test_second_concurrent_instance_is_rejected_then_third_succeeds_after_release(self) -> None:
        first_ctx = self._run(bootstrap_persistence(self.database_url))
        try:
            with self.assertRaises(SingletonLockError):
                self._run(bootstrap_persistence(self.database_url))
        finally:
            self._run(first_ctx.close())

        # The lock was released when first_ctx closed — a fresh instance must be able to start.
        third_ctx = self._run(bootstrap_persistence(self.database_url))
        self._run(third_ctx.close())


if __name__ == "__main__":
    unittest.main()
