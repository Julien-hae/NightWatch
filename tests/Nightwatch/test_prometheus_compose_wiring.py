"""Static test that prometheus.yml scrape targets reference defined compose services."""

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
COMPOSE_PATH = ROOT / "docker-compose.yml"
PROMETHEUS_PATH = ROOT / "src" / "Nightwatch" / "metrics" / "prometheus.yml"


class TestPrometheusComposeWiring(unittest.TestCase):
    """Ensure every non-localhost scrape target in prometheus.yml maps to a compose service."""

    def test_scrape_targets_match_compose_services(self) -> None:
        compose_text = COMPOSE_PATH.read_text()
        prom_text = PROMETHEUS_PATH.read_text()

        # Extract top-level service names from docker-compose.yml
        service_names: set[str] = set()
        in_services = False
        for line in compose_text.splitlines():
            if line.rstrip() == "services:":
                in_services = True
                continue
            if in_services:
                # A top-level key under services: is indented exactly 2 spaces
                match = re.match(r"^  (\w[\w-]*):", line)
                if match:
                    service_names.add(match.group(1))
                elif line and not line.startswith(" "):
                    break  # Left the services block

        # Extract targets from prometheus.yml (e.g. ["host:port"])
        targets = re.findall(r'targets:\s*\["([^"]+)"', prom_text)

        for target in targets:
            host = target.split(":")[0]
            if host in ("localhost", "127.0.0.1"):
                continue
            self.assertIn(
                host,
                service_names,
                msg=f"Scrape target '{target}' references host '{host}' which is not a defined compose service",
            )


if __name__ == "__main__":
    unittest.main()
