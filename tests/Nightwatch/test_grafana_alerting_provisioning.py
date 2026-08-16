"""Static tests for Grafana-provisioned alert rules.

Part of the production readiness audit remediation: prometheus.yml shipped with
an empty `rule_files`/`alertmanagers` and no Alertmanager service existed
anywhere in the stack, so a real Postgres or trade-service outage had nothing
in this repo that would ever page anyone. Alerting is provisioned through
Grafana's unified alerting instead (no extra service required) — validated by
running this exact file against a real `grafana/grafana:11.1.4` container and
confirming both rules load with `provenance: "file"` via the alerting API.

Asserts on the provisioning files as plain text, matching the style of
test_grafana_compose_wiring.py / test_prometheus_compose_wiring.py.
"""

import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
ALERT_RULES_PATH = ROOT / "grafana" / "provisioning" / "alerting" / "rules.yml"
DATASOURCE_PATH = ROOT / "grafana" / "provisioning" / "datasources" / "datasource.yml"


class TestGrafanaAlertingProvisioning(unittest.TestCase):
    """Ensure the two safety-critical alert rules are provisioned and well-formed."""

    def test_datasource_has_a_stable_uid_for_alert_rules_to_reference(self) -> None:
        """Alert rules pin datasourceUid: prometheus, so the datasource needs that uid."""
        self.assertTrue(DATASOURCE_PATH.exists(), msg="Grafana datasource provisioning file is missing")
        datasource_text = DATASOURCE_PATH.read_text()

        self.assertIn("uid: prometheus", datasource_text)

    def test_alert_rules_file_exists_and_targets_the_nightwatch_folder(self) -> None:
        self.assertTrue(ALERT_RULES_PATH.exists(), msg="Grafana alerting rules file is missing")
        rules_text = ALERT_RULES_PATH.read_text()

        self.assertIn("apiVersion: 1", rules_text)
        self.assertIn("folder: NightWatch", rules_text)

    def test_trade_service_down_rule_queries_the_up_metric(self) -> None:
        rules_text = ALERT_RULES_PATH.read_text()

        self.assertIn("uid: nw-trade-service-down", rules_text)
        self.assertIn('expr: up{job="trade-service"}', rules_text)

    def test_postgres_unreachable_rule_queries_db_up(self) -> None:
        rules_text = ALERT_RULES_PATH.read_text()

        self.assertIn("uid: nw-postgres-unreachable", rules_text)
        self.assertIn("expr: db_up", rules_text)

    def test_both_rules_have_a_for_duration_and_critical_severity(self) -> None:
        """A rule with no `for:` fires on a single scrape blip; require a debounce window."""
        rules_text = ALERT_RULES_PATH.read_text()

        self.assertEqual(rules_text.count("for: 2m"), 2, msg="expected both rules to debounce for 2m before firing")
        self.assertEqual(rules_text.count("severity: critical"), 2)

    def test_both_rules_alert_on_no_data_and_eval_errors(self) -> None:
        """A missing/errored query must not be mistaken for a healthy metric."""
        rules_text = ALERT_RULES_PATH.read_text()

        self.assertEqual(rules_text.count("noDataState: Alerting"), 2, msg="both rules must alert on no data, not silently pass")
        self.assertEqual(rules_text.count("execErrState: Alerting"), 2, msg="both rules must alert on query errors, not silently pass")

    def test_alerting_directory_is_covered_by_the_existing_compose_mount(self) -> None:
        """grafana/provisioning is mounted wholesale, so no extra compose change is needed."""
        compose_text = (ROOT / "docker-compose.yml").read_text()

        self.assertIn("./grafana/provisioning:/etc/grafana/provisioning:ro", compose_text)


if __name__ == "__main__":
    unittest.main()
