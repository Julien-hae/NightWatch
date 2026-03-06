"""Tests for the KrakenAdapter class."""

import asyncio
import json
import unittest
from datetime import datetime
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

from Nightwatch.kraken_adapter import KrakenAdapter
from Nightwatch.metrics import NightwatchMetrics
from Nightwatch.models.market_tick import MarketTick


class TestKrakenAdapter(unittest.TestCase):
    """Unit tests for the KrakenAdapter class."""

    def setUp(self) -> None:
        """Set up the KrakenAdapter instance for testing."""
        self.adapter = KrakenAdapter()

    def test_parse_message(self) -> None:
        """Test the parse_message method of the KrakenAdapter class."""
        message: Dict[str, Any] = {
            "channel": "ticker",
            "type": "snapshot",
            "data": [
                {
                    "symbol": "BTC/USD",
                    "bid": 0.10025,
                    "bid_qty": 740.0,
                    "ask": 0.10036,
                    "ask_qty": 1361.44813783,
                    "last": 0.10035,
                    "volume": 997038.98383185,
                    "vwap": 0.10148,
                    "low": 0.09979,
                    "high": 0.10285,
                    "change": -0.00017,
                    "change_pct": -0.17,
                    "timestamp": "2023-09-25T09:04:31.742648Z",
                }
            ],
        }
        market_tick = self.adapter.parse_message(message)
        if market_tick is None:
            self.fail("parse_message returned None for a valid message")
        self.assertIsInstance(market_tick, MarketTick)
        self.assertEqual(market_tick.symbol, "BTC/USD")
        self.assertEqual(market_tick.price, 0.10035)
        data_list = message["data"]
        dt = datetime.fromisoformat(data_list[0]["timestamp"].replace("Z", "+00:00"))
        self.assertEqual(market_tick.timestamp, dt)

    def test_parse_heartbeat_message(self) -> None:
        """Test the parse_message method of the KrakenAdapter class with a heartbeat message."""
        message = {"channel": "heartbeat"}
        market_tick = self.adapter.parse_message(message)
        self.assertIsNone(market_tick)

    def test_parse_invalid_message(self) -> None:
        """Test the parse_message method of the KrakenAdapter class with an invalid message."""
        message = {"invalid": "message"}
        market_tick = self.adapter.parse_message(message)
        self.assertIsNone(market_tick)

    def test_parse_none_message(self) -> None:
        """Test the parse_message method of the KrakenAdapter class with a None message."""
        market_tick = self.adapter.parse_message(None)
        self.assertIsNone(market_tick)

    @patch("Nightwatch.kraken_adapter.connect", new_callable=AsyncMock)
    def test_connect(self, mock_connect: AsyncMock) -> None:
        """Test the connect method of the KrakenAdapter class."""
        mock_ws = AsyncMock()
        mock_connect.return_value = mock_ws
        asyncio.run(self.adapter.connect())
        mock_connect.assert_called_once_with(self.adapter.uri, max_size=1048576)
        self.assertEqual(self.adapter.websocket, mock_ws)

    def test_subscribe(self) -> None:
        """Test the subscribe method of the KrakenAdapter class."""
        mock_ws = AsyncMock()
        self.adapter.websocket = mock_ws
        asyncio.run(self.adapter.subscribe())
        mock_ws.send.assert_called_once()

    def test_close(self) -> None:
        """Test the close method of the KrakenAdapter class."""
        mock_ws = AsyncMock()
        self.adapter.websocket = mock_ws
        asyncio.run(self.adapter.close())
        mock_ws.close.assert_called_once()

    def test_integration_receive_at_least_one_message(self) -> None:
        """
        Integration test: Connect to Kraken, subscribe to BTC/USD, and receive at least 1 message within 10 seconds.
        Note: This test requires a real internet connection and may be slow/flaky. Run sparingly.
        """

        async def run_integration() -> List[str]:
            await self.adapter.connect()
            await self.adapter.subscribe()
            if self.adapter.websocket is None:
                raise ConnectionError("WebSocket not connected. Call connect() first.")

            messages = []
            try:
                async for message in self.adapter.websocket:
                    if isinstance(message, str):
                        messages.append(message)
                        break
            finally:
                if self.adapter.websocket:
                    await self.adapter.close()
            return messages

        messages = asyncio.run(asyncio.wait_for(run_integration(), timeout=10))
        self.assertGreaterEqual(len(messages), 1, "Did not receive at least 1 message within 10 seconds")

    def test_integration_parse_real_message(self) -> None:
        """
        Integration test: Connect to Kraken, subscribe to BTC/USD, receive a message, and parse it.
        Note: This test requires a real internet connection and may be slow/flaky. Run sparingly.
        """

        async def run_integration() -> Any:
            await self.adapter.connect()
            await self.adapter.subscribe()

            if not self.adapter.websocket:
                raise ConnectionError("WebSocket not connected. Call connect() first.")

            market_tick = None
            try:
                async for tmp_message in self.adapter.websocket:
                    if isinstance(tmp_message, str):
                        print(f"Received message: {tmp_message}")
                        message = json.loads(tmp_message)
                        if message.get("channel", "") == "ticker":
                            market_tick = self.adapter.parse_message(message)
                            if market_tick:
                                break
            finally:
                if self.adapter.websocket:
                    await self.adapter.close()
            return market_tick

        market_tick = asyncio.run(asyncio.wait_for(run_integration(), timeout=15))
        self.assertIsNotNone(market_tick, "Did not receive a valid MarketTick within 10 seconds")
        self.assertEqual(market_tick.symbol, "BTC/USD")

    def test_parse_error_increments_metric(self) -> None:
        """Given a malformed message, when parsed, then parse_errors_total increments."""
        metrics = NightwatchMetrics()
        adapter = KrakenAdapter(metrics=metrics)

        before = metrics.parse_errors_total._value.get()
        adapter.parse_message({"channel": "ticker", "data": [{"key": "value"}]})
        after = metrics.parse_errors_total._value.get()
        self.assertEqual(after - before, 1.0)

    def test_valid_parse_does_not_increment_error_metric(self) -> None:
        """Given a valid message, when parsed, then parse_errors_total stays at 0."""
        metrics = NightwatchMetrics()
        adapter = KrakenAdapter(metrics=metrics)

        valid_message = {
            "channel": "ticker",
            "data": [
                {
                    "symbol": "BTC/USD",
                    "last": "65000.0",
                    "timestamp": "2023-09-25T09:04:31.742648Z",
                }
            ],
        }
        adapter.parse_message(valid_message)
        self.assertEqual(metrics.parse_errors_total._value.get(), 0.0)

    def test_no_metrics_does_not_crash(self) -> None:
        """Given no metrics injected, when a bad message arrives, then no AttributeError."""
        adapter = KrakenAdapter()  # metrics=None
        result = adapter.parse_message({"channel": "ticker", "data": []})
        self.assertIsNone(result)

    def test_no_metrics_does_not_crash_with_invalid_data(self) -> None:
        """Given no metrics injected, when a bad message arrives, then no AttributeError."""
        adapter = KrakenAdapter()  # metrics=None
        result = adapter.parse_message({"channel": "ticker", "data": ["invalid"]})
        self.assertIsNone(result)
