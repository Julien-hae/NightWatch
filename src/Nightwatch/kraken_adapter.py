"""KrakenAdapter module."""

import asyncio
import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, AsyncIterator, Dict, Optional

from websockets import connect
from websockets.asyncio.client import ClientConnection

from Nightwatch.exchange_market_adapter import ExchangeMarketAdapter
from Nightwatch.metrics import NightwatchMetrics
from Nightwatch.models.market_tick import MarketTick

LOGGER = logging.getLogger(__name__)


class KrakenAdapter(ExchangeMarketAdapter):
    """Adapter to ingest live stock data from the Kraken API."""

    def __init__(self, symbol: str = "BTC/USD", metrics: Optional[NightwatchMetrics] = None) -> None:
        """Initialize the KrakenAdapter class."""
        super().__init__()
        self.websocket: Optional[ClientConnection] = None
        self.uri = "wss://ws.kraken.com/v2"
        self.symbol = symbol
        self._metrics = metrics

    async def connect(self) -> None:
        """Connect to the Kraken websocket."""
        try:
            self.websocket = await connect(self.uri)
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Kraken websocket: {e}") from e

    async def subscribe(self) -> None:
        """Subscribe to the self.symbol ticker."""
        if self.websocket is None:
            raise ConnectionError("WebSocket not connected. Call connect() first.")
        subscribe_message = {
            "method": "subscribe",
            "params": {
                "channel": "ticker",
                "symbol": [self.symbol],
            },
        }
        await self.websocket.send(json.dumps(subscribe_message))

    def parse_message(self, message: Optional[Dict[str, Any]]) -> Optional[MarketTick]:
        """Parse a message received from the websocket and return a MarketTick, or None for non-ticker messages."""
        if not isinstance(message, dict):
            return None
        if message.get("channel") != "ticker":
            return None
        data = message.get("data")
        if not data or not isinstance(data, list) or len(data) == 0:
            return None
        entry = data[0]
        if not isinstance(entry, dict):
            return None
        try:
            ts_str = entry.get("timestamp", "")
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            return MarketTick(
                symbol=entry.get("symbol", ""),
                price=Decimal(entry.get("last", 0)),
                timestamp=dt,
                source="Kraken",
                schema_version=1,
            )
        except (KeyError, ValueError, TypeError) as exc:
            if self._metrics is not None:
                self._metrics.parse_errors_total.inc()
            LOGGER.error("Error parsing message: %s. Exception: %s", message, exc)
        return None

    async def close(self) -> None:
        """Close the Kraken websocket connection, if open."""
        if self.websocket is not None:
            try:
                await self.websocket.close()
            finally:
                self.websocket = None

    async def stream_ticks(self) -> AsyncIterator[MarketTick]:
        """Yield a continuous stream of validated pydantic MarketTick objects.

        Connects and subscribes automatically on first call.
        Skips control / heartbeat messages.
        Runs indefinitely until the caller breaks out or the websocket closes.
        """
        if self.websocket is None:
            await self.connect()
            await self.subscribe()

        while True:
            raw = await asyncio.wait_for(self.websocket.recv(), timeout=15)  # type: ignore[union-attr]
            parsed = self.parse_message(json.loads(raw))
            if parsed is not None:
                if self._metrics is not None:
                    self._metrics.ticks_received_total.inc()
                yield parsed
