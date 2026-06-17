"""Integration tests for the /healthz endpoint with a real Postgres database.

Requires both ``RUN_INTEGRATION=1`` and a reachable Postgres pointed to by
``DATABASE_URL`` (e.g. the ``trade-db`` service in ``docker-compose.yml``).
"""

import os
import unittest

from fastapi.testclient import TestClient

from Nightwatch.api import create_app
from Nightwatch.database import DatabaseConnector
from Nightwatch.models.service_health import ServiceHealth


@unittest.skipUnless(os.environ.get("RUN_INTEGRATION"), "Integration tests require RUN_INTEGRATION=1")
class TestHealthzDatabaseIntegration(unittest.TestCase):
    """Drive /healthz against a live Postgres instance."""

    def setUp(self) -> None:
        self.database_url = os.environ.get("DATABASE_URL")
        if not self.database_url:
            self.skipTest("DATABASE_URL is not set; cannot run DB integration tests")

    def test_healthz_reports_db_connected_true_when_db_is_up(self) -> None:
        health = ServiceHealth(ws_connected=True, nats_connected=True, db_connected=False)
        db = DatabaseConnector(database_url=self.database_url)
        client = TestClient(create_app(health=health, database=db))
        try:
            response = client.get("/healthz")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["db_connected"])

    def test_healthz_reports_db_connected_false_when_db_is_down(self) -> None:
        # Point at an unreachable host/port so asyncpg fails fast.
        bad_url = "postgresql+asyncpg://trade:tradepass@127.0.0.1:1/trade"
        health = ServiceHealth(ws_connected=True, nats_connected=True, db_connected=True)
        db = DatabaseConnector(database_url=bad_url, timeout=1.0)
        client = TestClient(create_app(health=health, database=db))
        try:
            response = client.get("/healthz")
        finally:
            client.close()

        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertFalse(body["db_connected"])
