"""Static tests for .github/workflows/ci.yml.

Part of the production readiness audit remediation: base-image OS packages
were not scanned by anything in this repo (only Python dependencies, via
manual `pip-audit`). Asserts on the workflow file as plain text, matching the
style of test_docker_compose_restart_policy.py.
"""

import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
CI_WORKFLOW_PATH = ROOT / ".github" / "workflows" / "ci.yml"


class TestContainerVulnerabilityScanning(unittest.TestCase):
    """The built image must be scanned for known vulnerabilities."""

    def setUp(self) -> None:
        self.workflow_text = CI_WORKFLOW_PATH.read_text()

    def test_container_scan_job_exists(self) -> None:
        self.assertIn("container-scan:", self.workflow_text)
        self.assertIn("trivy", self.workflow_text.lower())

    def test_scan_builds_the_actual_dockerfile(self) -> None:
        job_idx = self.workflow_text.index("container-scan:")
        next_job_idx = self.workflow_text.index("\n  quality:", job_idx)
        job_block = self.workflow_text[job_idx:next_job_idx]

        self.assertIn("docker build", job_block)

    def test_scan_is_report_only_not_a_merge_gate(self) -> None:
        """A hard-fail-on-any-CVE gate would make CI red for reasons unrelated to code
        changes — base-image OS packages and Python deps will always carry some
        CRITICAL/HIGH CVEs, often with no upstream fix yet."""
        job_idx = self.workflow_text.index("container-scan:")
        next_job_idx = self.workflow_text.index("\n  quality:", job_idx)
        job_block = self.workflow_text[job_idx:next_job_idx]

        self.assertIn('exit-code: "0"', job_block)

    def test_scan_results_are_uploaded_for_visibility(self) -> None:
        job_idx = self.workflow_text.index("container-scan:")
        next_job_idx = self.workflow_text.index("\n  quality:", job_idx)
        job_block = self.workflow_text[job_idx:next_job_idx]

        self.assertIn("upload-sarif", job_block)
        self.assertIn("security-events: write", job_block)


if __name__ == "__main__":
    unittest.main()
