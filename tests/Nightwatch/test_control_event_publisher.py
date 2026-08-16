# mypy: disable-error-code="import-untyped"
"""Unit tests for ControlEventPublisher's connect-guard logic (no real NATS needed)."""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from Nightwatch.messaging.control_event_publisher import ControlEventPublisher


class TestSetupStreamConnectGuard(unittest.TestCase):
    """setup_stream() must not re-connect an already-connected client.

    Calling connect() on a client that isn't fully closed races nats-py's own
    internal reconnect loop — see the identical guard in api.py's startup handler.
    """

    def _make_publisher(self, *, is_closed: bool) -> tuple[ControlEventPublisher, AsyncMock]:
        publisher = ControlEventPublisher()
        mock_client = MagicMock()
        mock_client.is_closed = is_closed
        mock_jetstream = MagicMock()
        mock_jetstream.stream_info = AsyncMock(return_value=MagicMock())
        mock_client.jetstream.return_value = mock_jetstream
        publisher._nc = mock_client  # noqa: SLF001

        connect_mock = AsyncMock()
        publisher.connect = connect_mock  # type: ignore[method-assign]
        return publisher, connect_mock

    def test_skips_connect_when_client_already_connected(self) -> None:
        publisher, connect_mock = self._make_publisher(is_closed=False)

        asyncio.run(publisher.setup_stream())

        connect_mock.assert_not_awaited()

    def test_connects_when_client_is_closed(self) -> None:
        publisher, connect_mock = self._make_publisher(is_closed=True)

        asyncio.run(publisher.setup_stream())

        connect_mock.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
