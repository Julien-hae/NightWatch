"""Unit tests for the /healthz and /metrics endpoints."""

import unittest

from fastapi.testclient import TestClient

from Nightwatch.api import create_app
from Nightwatch.metrics import NightwatchMetrics
from Nightwatch.models.service_health import ServiceHealth


class TestHealthEndpoint(unittest.TestCase):
    def test_healthz_returns_200(self) -> None:
        health = ServiceHealth(ws_connected=False, nats_connected=False)
        client = TestClient(create_app(health=health))

        response = client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"ws_connected": False, "nats_connected": False},
        )

    def test_healthz_reflects_connected_state(self) -> None:
        health = ServiceHealth(ws_connected=True, nats_connected=True)
        client = TestClient(create_app(health=health))

        response = client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"ws_connected": True, "nats_connected": True},
        )


class TestMetricsEndpoint(unittest.TestCase):
    def test_metrics_returns_200(self) -> None:
        client = TestClient(create_app())

        response = client.get("/metrics")

        self.assertEqual(response.status_code, 200)

    def test_metrics_contains_expected_counters(self) -> None:
        metrics = NightwatchMetrics()
        client = TestClient(create_app(metrics=metrics))

        response = client.get("/metrics")

        body = response.text
        self.assertIn("ticks_received_total", body)
        self.assertIn("parse_errors_total", body)
        self.assertIn("ws_reconnects_total", body)

    def test_metrics_reflects_incremented_counters(self) -> None:
        metrics = NightwatchMetrics()
        metrics.ticks_received_total.inc(5)
        metrics.parse_errors_total.inc(2)
        metrics.ws_reconnects_total.inc(1)
        client = TestClient(create_app(metrics=metrics))

        response = client.get("/metrics")

        body = response.text
        self.assertIn("ticks_received_total 5.0", body)
        self.assertIn("parse_errors_total 2.0", body)
        self.assertIn("ws_reconnects_total 1.0", body)
