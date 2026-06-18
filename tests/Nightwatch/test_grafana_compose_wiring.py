"""Static tests for Grafana compose wiring and datasource provisioning."""

import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
COMPOSE_PATH = ROOT / "docker-compose.yml"
DATASOURCE_PATH = ROOT / "grafana" / "provisioning" / "datasources" / "datasource.yml"
DASHBOARD_PROVIDER_PATH = ROOT / "grafana" / "provisioning" / "dashboards" / "dashboards.yml"
DASHBOARD_JSON_PATH = ROOT / "grafana" / "provisioning" / "dashboards" / "nightwatch-overview.json"


class TestGrafanaComposeWiring(unittest.TestCase):
    """Ensure Grafana is wired for automatic Prometheus datasource provisioning."""

    def test_compose_includes_grafana_service_with_expected_wiring(self) -> None:
        compose_text = COMPOSE_PATH.read_text()

        self.assertIn("  grafana:\n", compose_text)
        self.assertIn("    image: grafana/grafana:11.1.4\n", compose_text)
        self.assertIn('      - "3000:3000"\n', compose_text)
        self.assertIn("./grafana/provisioning:/etc/grafana/provisioning:ro", compose_text)
        self.assertIn("/api/health", compose_text)

    def test_datasource_file_defines_default_prometheus_datasource(self) -> None:
        self.assertTrue(DATASOURCE_PATH.exists(), msg="Grafana datasource provisioning file is missing")
        datasource_text = DATASOURCE_PATH.read_text()

        self.assertIn("apiVersion: 1", datasource_text)
        self.assertIn("name: Prometheus", datasource_text)
        self.assertIn("type: prometheus", datasource_text)
        self.assertIn("access: proxy", datasource_text)
        self.assertIn("url: http://prometheus:9090", datasource_text)
        self.assertIn("isDefault: true", datasource_text)

    def test_dashboard_provisioning_files_exist_and_match_compose_mount(self) -> None:
        compose_text = COMPOSE_PATH.read_text()
        self.assertIn("./grafana/provisioning:/etc/grafana/provisioning:ro", compose_text)

        self.assertTrue(DASHBOARD_PROVIDER_PATH.exists(), msg="Grafana dashboard provider file is missing")
        provider_text = DASHBOARD_PROVIDER_PATH.read_text()
        self.assertIn("apiVersion: 1", provider_text)
        self.assertIn("type: file", provider_text)
        self.assertIn("path: /etc/grafana/provisioning/dashboards", provider_text)

        self.assertTrue(DASHBOARD_JSON_PATH.exists(), msg="Grafana dashboard JSON is missing")
        dashboard_text = DASHBOARD_JSON_PATH.read_text()
        self.assertIn('"title": "NightWatch Overview"', dashboard_text)


if __name__ == "__main__":
    unittest.main()
