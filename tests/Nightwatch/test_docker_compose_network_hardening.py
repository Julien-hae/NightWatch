"""Static test asserting no docker-compose.yml port is reachable beyond localhost.

Part of the production-readiness audit remediation: the shipped compose file
used to publish every service's port on all interfaces (`"5432:5432"`, no
bind address), and NATS ran with no authentication at all. On a host with a
public IP and no external firewall, that meant anyone on the internet could
read/write Postgres directly or publish a fake kill-switch command. This
test guards against that regressing, in the same plain-text style as
test_grafana_compose_wiring.py / test_prometheus_compose_wiring.py.
"""

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
COMPOSE_PATH = ROOT / "docker-compose.yml"
ENV_EXAMPLE_PATH = ROOT / ".env.example"

_PORT_MAPPING_RE = re.compile(r'^\s*-\s*"([^"]+)"\s*$', re.MULTILINE)


class TestDockerComposeNetworkHardening(unittest.TestCase):
    """No published port may be reachable from beyond the host itself."""

    def test_every_published_port_is_bound_to_loopback(self) -> None:
        """Every `ports:` entry in docker-compose.yml must start with `127.0.0.1:`."""
        compose_text = COMPOSE_PATH.read_text()

        # A `ports:` mapping is either "host:container" or "bind:host:container"; any
        # entry containing a colon-separated port number that doesn't start with an
        # explicit loopback bind address is reachable from every interface on the host.
        mappings = [m for m in _PORT_MAPPING_RE.findall(compose_text) if re.match(r"^\d+:\d+$|^127\.0\.0\.1:\d+:\d+$", m)]
        self.assertGreater(len(mappings), 0, msg="No port mappings found — parsing regex may be stale")

        unbound = [m for m in mappings if not m.startswith("127.0.0.1:")]
        self.assertEqual(unbound, [], msg=f"Port(s) published without a loopback bind address: {unbound}")

    def test_nats_requires_authentication(self) -> None:
        """The nats service must be started with --auth, not bare `-js`."""
        compose_text = COMPOSE_PATH.read_text()

        nats_idx = compose_text.index("  nats:\n")
        next_service_idx = compose_text.index("\n  trade-service:\n", nats_idx)
        nats_block = compose_text[nats_idx:next_service_idx]

        self.assertIn("--auth", nats_block, msg="nats service must require a token (--auth) — it has no auth by default")
        self.assertIn("NATS_TOKEN", nats_block)

    def test_credentials_are_parameterized_not_hardcoded(self) -> None:
        """Postgres and Grafana passwords must come from env vars, not literal defaults in the file."""
        compose_text = COMPOSE_PATH.read_text()

        self.assertNotIn("POSTGRES_PASSWORD: tradepass\n", compose_text)
        self.assertIn("POSTGRES_PASSWORD: ${POSTGRES_PASSWORD", compose_text)
        self.assertNotIn("GF_SECURITY_ADMIN_PASSWORD: admin\n", compose_text)
        self.assertIn("GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD", compose_text)

    def test_env_example_documents_every_overridable_secret(self) -> None:
        """.env.example must exist and mention every secret docker-compose.yml reads from the environment."""
        self.assertTrue(ENV_EXAMPLE_PATH.exists(), msg=".env.example is missing")
        env_example_text = ENV_EXAMPLE_PATH.read_text()

        for var in ("POSTGRES_PASSWORD", "NATS_TOKEN", "GRAFANA_ADMIN_PASSWORD"):
            self.assertIn(var, env_example_text, msg=f"{var} is not documented in .env.example")


if __name__ == "__main__":
    unittest.main()
