"""Static tests for Dockerfile/compose hardening.

Part of the production readiness audit remediation: the shipped Dockerfile ran
as root with no HEALTHCHECK, docker-compose.yml's trade-service had no
healthcheck (unlike trade-db/loki/grafana, which do), and there was no
.dockerignore — meaning the full build context (.git, .venv, any local
credentials.env) was sent to the Docker daemon on every build. Asserts on the
files as plain text, matching the style of test_docker_compose_restart_policy.py.
"""

import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
DOCKERFILE_PATH = ROOT / "Dockerfile"
COMPOSE_PATH = ROOT / "docker-compose.yml"
DOCKERIGNORE_PATH = ROOT / ".dockerignore"


class TestDockerfileHardening(unittest.TestCase):
    """The built image must not run as root and must expose a HEALTHCHECK."""

    def test_dockerfile_declares_a_non_root_user(self) -> None:
        dockerfile_text = DOCKERFILE_PATH.read_text()

        self.assertIn("USER nightwatch", dockerfile_text)
        self.assertIn("useradd", dockerfile_text)

    def test_dockerfile_declares_a_healthcheck(self) -> None:
        dockerfile_text = DOCKERFILE_PATH.read_text()

        self.assertIn("HEALTHCHECK", dockerfile_text)
        self.assertIn("/healthz", dockerfile_text)

    def test_user_is_declared_after_dependency_install(self) -> None:
        """USER must come after `poetry install`, or the app installs as an unprivileged
        user with no permission to write site-packages."""
        dockerfile_text = DOCKERFILE_PATH.read_text()

        install_idx = dockerfile_text.index("poetry install --only main\n")
        user_idx = dockerfile_text.index("USER nightwatch")
        self.assertLess(install_idx, user_idx)


class TestDockerComposeHealthcheck(unittest.TestCase):
    """trade-service must have the same kind of healthcheck as every other service."""

    def test_trade_service_has_a_healthcheck(self) -> None:
        compose_text = COMPOSE_PATH.read_text()

        service_idx = compose_text.index("  trade-service:\n")
        next_service_idx = compose_text.index("\n  loki:\n", service_idx)
        service_block = compose_text[service_idx:next_service_idx]

        self.assertIn("healthcheck:", service_block)
        self.assertIn("/healthz", service_block)


class TestDockerignore(unittest.TestCase):
    """The build context must not include VCS/venv/cache/secret files."""

    def test_dockerignore_exists_and_excludes_sensitive_paths(self) -> None:
        self.assertTrue(DOCKERIGNORE_PATH.exists(), msg=".dockerignore is missing")
        dockerignore_text = DOCKERIGNORE_PATH.read_text()

        for entry in (".git", ".venv", "*.env", "credentials.env", ".mypy_cache"):
            self.assertIn(entry, dockerignore_text, msg=f"{entry} is not excluded from the Docker build context")


if __name__ == "__main__":
    unittest.main()
