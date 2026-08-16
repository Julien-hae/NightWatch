"""Unit tests for the /healthz and /metrics endpoints."""

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from Nightwatch.api import create_app
from Nightwatch.db.database import DatabaseConnector
from Nightwatch.metrics.metrics import NightwatchMetrics
from Nightwatch.models.service_health import ServiceHealth


class _StubDatabase(DatabaseConnector):
    """DatabaseConnector test double whose ping result can change between calls."""

    def __init__(self, result: bool) -> None:
        super().__init__(database_url="postgresql://stub/stub")
        self.result = result
        self.calls = 0

    async def ping(self) -> bool:
        self.calls += 1
        return self.result


class TestHealthEndpoint(unittest.TestCase):
    """Tests for the /healthz endpoint to ensure it returns the correct health status."""

    def setUp(self) -> None:
        self._env_patcher = patch.dict(os.environ, {"NATS_SERVERS": ""})
        self._env_patcher.start()
        self.health = ServiceHealth(ws_connected=False, nats_connected=False, db_connected=False)
        self.client = TestClient(create_app(health=self.health))

    def tearDown(self) -> None:
        self.client.close()
        self._env_patcher.stop()

    def test_healthz_returns_503_when_unhealthy(self) -> None:
        response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {"ok": False, "ws_connected": False, "nats_connected": False, "db_connected": False},
        )

    def test_healthz_returns_200_when_all_connected(self) -> None:
        self.health.ws_connected = True
        self.health.nats_connected = True
        self.health.db_connected = True
        response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"ok": True, "ws_connected": True, "nats_connected": True, "db_connected": True},
        )

    def test_healthz_503_when_only_db_disconnected(self) -> None:
        self.health.ws_connected = True
        self.health.nats_connected = True
        self.health.db_connected = False
        response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertFalse(body["db_connected"])

    def test_healthz_503_when_only_nats_disconnected(self) -> None:
        self.health.ws_connected = True
        self.health.nats_connected = False
        self.health.db_connected = True
        response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertFalse(body["nats_connected"])


@patch.dict(os.environ, {"NATS_SERVERS": ""})
class TestHealthEndpointWithDatabase(unittest.TestCase):
    """Tests for the /healthz endpoint when a DatabaseConnector is injected."""

    def test_db_connected_true_when_ping_succeeds(self) -> None:
        health = ServiceHealth(ws_connected=True, nats_connected=True, db_connected=False)
        db = _StubDatabase(result=True)
        client = TestClient(create_app(health=health, database=db))
        try:
            response = client.get("/healthz")
        finally:
            client.close()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["db_connected"])
        self.assertEqual(db.calls, 1)

    def test_db_connected_false_when_ping_fails(self) -> None:
        health = ServiceHealth(ws_connected=True, nats_connected=True, db_connected=True)
        db = _StubDatabase(result=False)
        client = TestClient(create_app(health=health, database=db))
        try:
            response = client.get("/healthz")
        finally:
            client.close()

        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertFalse(body["db_connected"])

    def test_db_up_metric_tracks_live_outage_with_externally_injected_database(self) -> None:
        """db_up must update on every poll, matching main.py's real wiring: a pre-built
        DatabaseConnector passed in via database=, not bootstrapped by create_app itself
        (that internal-bootstrap path is the only one the old code kept db_up in sync with).
        """
        health = ServiceHealth(ws_connected=True, nats_connected=True, db_connected=True)
        db = _StubDatabase(result=True)
        metrics = NightwatchMetrics()
        client = TestClient(create_app(health=health, metrics=metrics, database=db))
        try:
            client.get("/healthz")
            self.assertEqual(metrics.db_up._value.get(), 1.0)

            db.result = False
            client.get("/healthz")
            self.assertEqual(metrics.db_up._value.get(), 0.0, "db_up must flip to 0 on a live outage, not stay frozen")

            db.result = True
            client.get("/healthz")
            self.assertEqual(metrics.db_up._value.get(), 1.0, "db_up must recover once the ping succeeds again")
        finally:
            client.close()


class TestMetricsEndpoint(unittest.TestCase):
    """Tests for the /metrics endpoint to ensure it returns Prometheus metrics correctly."""

    def setUp(self) -> None:
        self.metrics = NightwatchMetrics()
        self.client = TestClient(create_app(metrics=self.metrics))

    def tearDown(self) -> None:
        self.client.close()

    def test_metrics_returns_200(self) -> None:
        response = self.client.get("/metrics")

        self.assertEqual(response.status_code, 200)

    def test_metrics_contains_expected_counters(self) -> None:
        response = self.client.get("/metrics")

        body = response.text
        self.assertIn("ticks_received_total", body)
        self.assertIn("parse_errors_total", body)
        self.assertIn("ws_reconnects_total", body)
        self.assertIn("ticks_consumed_total", body)
        self.assertIn("ticks_published_total", body)

    def test_metrics_reflects_incremented_counters(self) -> None:
        self.metrics.ticks_received_total.labels(symbol="BTC/USD").inc(5)
        self.metrics.parse_errors_total.inc(2)
        self.metrics.ws_reconnects_total.inc(1)
        response = self.client.get("/metrics")

        body = response.text
        self.assertIn('ticks_received_total{symbol="BTC/USD"} 5.0', body)
        self.assertIn("parse_errors_total 2.0", body)
        self.assertIn("ws_reconnects_total 1.0", body)
        self.assertIn("ticks_consumed_total", body)
        self.assertIn("ticks_published_total", body)

    def test_metrics_reflects_incremented_labeled_counters(self) -> None:
        self.metrics.ticks_consumed_total.labels(symbol="BTC/USD").inc(3)
        self.metrics.ticks_consumed_total.labels(symbol="ETH/USD").inc(7)
        self.metrics.ticks_published_total.labels(symbol="BTC/USD").inc(4)
        self.metrics.ticks_published_total.labels(symbol="ETH/USD").inc(2)
        response = self.client.get("/metrics")

        body = response.text
        self.assertIn('ticks_consumed_total{symbol="BTC/USD"} 3.0', body)
        self.assertIn('ticks_consumed_total{symbol="ETH/USD"} 7.0', body)
        self.assertIn('ticks_published_total{symbol="BTC/USD"} 4.0', body)
        self.assertIn('ticks_published_total{symbol="ETH/USD"} 2.0', body)
