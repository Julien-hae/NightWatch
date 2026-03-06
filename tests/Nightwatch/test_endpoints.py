"""Unit tests for the /healthz and /metrics endpoints."""

import unittest

from fastapi.testclient import TestClient

from Nightwatch.api import create_app
from Nightwatch.metrics import NightwatchMetrics
from Nightwatch.models.service_health import ServiceHealth


class TestHealthEndpoint(unittest.TestCase):
    """Tests for the /healthz endpoint to ensure it returns the correct health status."""

    def setUp(self) -> None:
        """Set up any necessary state before each test."""
        self.health = ServiceHealth(ws_connected=False, nats_connected=False)
        self.client = TestClient(create_app(health=self.health))

    def test_healthz_returns_200(self) -> None:
        """The /healthz endpoint should return a 200 OK status."""
        response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"ws_connected": False, "nats_connected": False},
        )

    def test_healthz_reflects_connected_state(self) -> None:
        """When the health state is updated to connected, /healthz should reflect that."""
        self.health.ws_connected = True
        self.health.nats_connected = True
        response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"ws_connected": True, "nats_connected": True},
        )

    def test_healthz_partial_connected_state_to_websockets(self) -> None:
        """When the health state is partially connected, /healthz should reflect that."""
        self.health.ws_connected = True
        self.health.nats_connected = False
        response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"ws_connected": True, "nats_connected": False},
        )

    def test_healthz_partial_connected_state_to_nats(self) -> None:
        """When the health state is partially connected, /healthz should reflect that."""
        self.health.ws_connected = False
        self.health.nats_connected = True
        response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"ws_connected": False, "nats_connected": True},
        )

    def tearDown(self) -> None:
        """Reset any global state if necessary after each test."""
        self.client.close()


class TestMetricsEndpoint(unittest.TestCase):
    """Tests for the /metrics endpoint to ensure it returns Prometheus metrics correctly."""

    def setUp(self) -> None:
        self.metrics = NightwatchMetrics()
        self.client = TestClient(create_app(metrics=self.metrics))

    def test_metrics_returns_200(self) -> None:
        """The /metrics endpoint should return a 200 OK status."""
        response = self.client.get("/metrics")

        self.assertEqual(response.status_code, 200)

    def test_metrics_contains_expected_counters(self) -> None:
        """The /metrics response should include the expected metric names."""
        response = self.client.get("/metrics")

        body = response.text
        self.assertIn("ticks_received_total", body)
        self.assertIn("parse_errors_total", body)
        self.assertIn("ws_reconnects_total", body)

    def test_metrics_reflects_incremented_counters(self) -> None:
        """After incrementing counters, the /metrics response should reflect the new values."""
        self.metrics.ticks_received_total.inc(5)
        self.metrics.parse_errors_total.inc(2)
        self.metrics.ws_reconnects_total.inc(1)
        response = self.client.get("/metrics")

        body = response.text
        self.assertIn("ticks_received_total 5.0", body)
        self.assertIn("parse_errors_total 2.0", body)
        self.assertIn("ws_reconnects_total 1.0", body)

    def tearDown(self) -> None:
        """Reset any global state if necessary after each test."""
        self.client.close()
