"""Fixture to manage a temporary nats-server process for integration tests."""

import socket
import subprocess
import time


class NatsServerFixture:
    """Manage a temporary nats-server process for integration tests."""

    def __init__(self) -> None:
        """Initialize the NatsServerFixture."""
        self.port: int = 0
        self._proc: subprocess.Popen[bytes] | None = None

    @property
    def url(self) -> str:
        """Return the NATS connection URL."""
        return f"nats://127.0.0.1:{self.port}"

    def _free_port(self) -> int:  # TODO: TOCTOU risk — replace with port-0 nats-server flag when available
        """Find a free TCP port on localhost."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port: int = s.getsockname()[1]
            return port

    def start(self) -> None:
        """Start nats-server on a random free port (or reuse the previous port on restart)."""
        if self.port == 0:
            self.port = self._free_port()
        try:
            self._proc = subprocess.Popen(
                ["nats-server", "-p", str(self.port)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "nats-server executable not found. Ensure nats-server is installed and available in PATH before running integration tests."
            ) from exc
        deadline = time.monotonic() + 5.0
        while True:
            if self._proc is not None and self._proc.poll() is not None:
                raise RuntimeError("nats-server process exited before it became ready")
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.5):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Timed out waiting for nats-server to become ready") from None
                time.sleep(0.05)

    def stop(self) -> None:
        """Gracefully stop nats-server (SIGTERM)."""
        if self._proc is not None:
            self._proc.terminate()
            self._proc.wait(timeout=5)
            self._proc = None

    def kill(self) -> None:
        """Force-kill nats-server (SIGKILL) to simulate a crash."""
        if self._proc is not None:
            self._proc.kill()
            self._proc.wait(timeout=5)
            self._proc = None
