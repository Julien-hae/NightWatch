"""Integration smoke tests for Grafana health and datasource provisioning."""

import base64
import json
import os
import unittest
import urllib.error
import urllib.request
from typing import Any


@unittest.skipUnless(os.environ.get("RUN_INTEGRATION"), "Integration tests require RUN_INTEGRATION=1")
class TestGrafanaProvisioningIntegration(unittest.TestCase):
    """Validate that Grafana boots healthy and auto-loads Prometheus datasource."""

    def setUp(self) -> None:
        self.base_url = os.environ.get("GRAFANA_URL", "http://127.0.0.1:3000").rstrip("/")
        self.admin_user = os.environ.get("GRAFANA_ADMIN_USER", "admin")
        self.admin_password = os.environ.get("GRAFANA_ADMIN_PASSWORD", "admin")

    def _get_payload(self, path: str, requires_auth: bool) -> object:
        request = urllib.request.Request(f"{self.base_url}{path}")

        if requires_auth:
            token = base64.b64encode(f"{self.admin_user}:{self.admin_password}".encode("utf-8")).decode("ascii")
            request.add_header("Authorization", f"Basic {token}")

        try:
            with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
                payload: Any = json.loads(response.read().decode("utf-8"))
                return payload
        except urllib.error.URLError as exc:
            self.skipTest(f"Grafana is not reachable at {self.base_url}. Start compose stack first. Details: {exc}")

    def _get_json(self, path: str, requires_auth: bool) -> dict[str, object]:
        payload = self._get_payload(path, requires_auth)
        if not isinstance(payload, dict):
            self.fail(f"Expected JSON object from {path}, got {type(payload).__name__}")
        return payload

    def test_grafana_health_endpoint_reports_ok(self) -> None:
        payload = self._get_json("/api/health", requires_auth=False)

        self.assertEqual(payload.get("database"), "ok")

    def test_prometheus_datasource_is_provisioned(self) -> None:
        payload = self._get_json("/api/datasources/name/Prometheus", requires_auth=True)

        self.assertEqual(payload.get("name"), "Prometheus")
        self.assertEqual(payload.get("type"), "prometheus")
        self.assertEqual(payload.get("access"), "proxy")
        self.assertEqual(payload.get("url"), "http://prometheus:9090")
        self.assertTrue(bool(payload.get("isDefault")))

    def test_nightwatch_dashboard_is_provisioned(self) -> None:
        payload = self._get_payload("/api/search?query=NightWatch%20Overview", requires_auth=True)
        if not isinstance(payload, list):
            self.fail(f"Expected dashboard search payload to be a list, got {type(payload).__name__}")

        titles = [item.get("title") for item in payload if isinstance(item, dict)]
        self.assertIn("NightWatch Overview", titles)

    def test_bot_health_dashboard_is_provisioned(self) -> None:
        payload = self._get_payload("/api/search?query=Bot%20Health", requires_auth=True)
        if not isinstance(payload, list):
            self.fail(f"Expected dashboard search payload to be a list, got {type(payload).__name__}")

        titles = [item.get("title") for item in payload if isinstance(item, dict)]
        self.assertIn("Bot Health", titles)

    def test_trading_dashboard_is_provisioned(self) -> None:
        payload = self._get_payload("/api/search?query=Trading", requires_auth=True)
        if not isinstance(payload, list):
            self.fail(f"Expected dashboard search payload to be a list, got {type(payload).__name__}")

        titles = [item.get("title") for item in payload if isinstance(item, dict)]
        self.assertIn("Trading", titles)


if __name__ == "__main__":
    unittest.main()
