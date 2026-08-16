"""Static test asserting every long-running docker-compose service restarts automatically.

Part of Phase 7 reliability ("bot runs 24/7 without manual babysitting"): a service that
crashes or is killed must come back on its own. This mirrors the plain-text assertion
style of test_grafana_compose_wiring.py / test_prometheus_compose_wiring.py rather than
parsing YAML, consistent with how those files already check docker-compose.yml.
"""

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
COMPOSE_PATH = ROOT / "docker-compose.yml"

_SERVICE_HEADER_RE = re.compile(r"^  (\w[\w-]*):\n", re.MULTILINE)


class TestDockerComposeRestartPolicy(unittest.TestCase):
    """Every service defined in docker-compose.yml must have `restart: unless-stopped`."""

    def test_every_service_has_restart_unless_stopped(self) -> None:
        """Given the compose file, when listing its services, then each one sets restart: unless-stopped."""
        compose_text = COMPOSE_PATH.read_text()
        # `volumes:` is a top-level (0-indent) key after `services:`; its entries are 2-space indented
        # too, so they'd otherwise be mistaken for service names by the header regex below.
        services_block = compose_text.split("\nvolumes:\n", 1)[0]
        services = [match.group(1) for match in _SERVICE_HEADER_RE.finditer(services_block)]

        self.assertGreater(len(services), 0, msg="No services found in docker-compose.yml — parsing regex may be stale")

        missing = [
            service
            for service, next_service in zip(services, [*services[1:], None])
            if "restart: unless-stopped" not in _service_block(services_block, service, next_service)
        ]
        self.assertEqual(missing, [], msg=f"Service(s) missing 'restart: unless-stopped': {missing}")


def _service_block(compose_text: str, service: str, next_service: str | None) -> str:
    """Return the text slice for *service*'s block, up to the next top-level service header (or EOF)."""
    start = compose_text.index(f"  {service}:\n")
    end = compose_text.index(f"  {next_service}:\n", start) if next_service is not None else len(compose_text)
    return compose_text[start:end]


if __name__ == "__main__":
    unittest.main()
