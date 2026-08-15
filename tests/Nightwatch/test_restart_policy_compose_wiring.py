"""Static test that every docker-compose service has an automatic restart policy.

Real container-kill-and-observe-restart testing needs a Docker daemon, which this
suite's unit tests don't have access to; the existing infra-as-code tests
(test_grafana_compose_wiring.py, test_prometheus_compose_wiring.py) instead assert
on docker-compose.yml as plain text, and this test follows the same pattern.
"""

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
COMPOSE_PATH = ROOT / "docker-compose.yml"


class TestRestartPolicyComposeWiring(unittest.TestCase):
    """Ensure every compose service restarts automatically after termination/crash."""

    def test_every_service_declares_restart_unless_stopped(self) -> None:
        compose_text = COMPOSE_PATH.read_text()

        service_names: list[str] = []
        service_blocks: dict[str, str] = {}
        in_services = False
        current_service: str | None = None
        current_lines: list[str] = []

        def _flush_current() -> None:
            if current_service is not None:
                service_blocks[current_service] = "\n".join(current_lines)

        for line in compose_text.splitlines():
            if line.rstrip() == "services:":
                in_services = True
                continue
            if not in_services:
                continue
            match = re.match(r"^  (\w[\w-]*):", line)
            if match:
                _flush_current()
                current_service = match.group(1)
                service_names.append(current_service)
                current_lines = []
            elif line and not line.startswith(" "):
                # Left the services block (e.g. reached "volumes:").
                break
            elif current_service is not None:
                current_lines.append(line)
        _flush_current()

        self.assertTrue(service_names, msg="No services found under docker-compose.yml's services: block")

        for name in service_names:
            self.assertIn(
                "    restart: unless-stopped",
                service_blocks[name],
                msg=f"Service '{name}' is missing 'restart: unless-stopped' — it won't recover automatically from a crash or host reboot.",
            )


if __name__ == "__main__":
    unittest.main()
