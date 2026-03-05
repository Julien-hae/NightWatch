"""KrakenAdapter module."""

import asyncio
import json
from datetime import datetime
from decimal import Decimal
from typing import Any, AsyncIterator, Dict, Optional

import pytz  # type: ignore[import-untyped]
from websockets import connect
from websockets.asyncio.client import ClientConnection

from Nightwatch.exchange_market_adapter import ExchangeMarketAdapter
from Nightwatch.models.market_tick import MarketTick


class KrakenAdapter(ExchangeMarketAdapter):
    """Adapter to ingest live stock data from the Kraken API."""

    def __init__(self, symbol: str = "BTC/USD") -> None:
        """Initialize the KrakenAdapter class."""
        super().__init__()
        self.websocket: Optional[ClientConnection] = None
        self.uri = "wss://ws.kraken.com/v2"
        self.symbol = symbol

    async def _connect_async(self) -> None:
        """Asynchronously connect to the Kraken websocket."""
        try:
            self.websocket = await connect(self.uri)
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Kraken websocket: {e}") from e

    def connect(self) -> None:
        """Connect to a Kraken websocket to receive live stock data."""
        asyncio.run(self._connect_async())

    async def _subscribe_async(self) -> None:
        """Asynchronously subscribe to the self.symbol ticker."""
        if not self.websocket:
            raise ConnectionError("WebSocket not connected. Call connect() first.")
        subscribe_message = {
            "method": "subscribe",
            "params": {
                "channel": "ticker",
                "symbol": [self.symbol],
            },
        }
        await self.websocket.send(json.dumps(subscribe_message))

    def subscribe(self) -> None:
        """Subscribe to a symbol to receive live stock data."""
        asyncio.run(self._subscribe_async())

    def parse_message(self, message: Optional[Dict[str, Any]]) -> Optional[MarketTick]:
        """Parse a message received from the websocket and return a MarketTick, or None for non-ticker messages."""
        if isinstance(message, dict) and message.get("data", None) is not None:
            if message.get("channel", "") == "ticker":
                naive_dt = datetime.fromisoformat(message["data"][0]["timestamp"].replace("Z", "+00:00"))
                aware_utc_dt = naive_dt.replace(tzinfo=pytz.utc)
                return MarketTick(
                    symbol=message["data"][0].get("symbol", ""),
                    price=Decimal(message["data"][0].get("last", 0)),
                    timestamp=aware_utc_dt,
                    source="Kraken",
                    schema_version=1,
                )
        return None

    async def _close_async(self) -> None:
        """Asynchronously close the Kraken websocket connection, if open."""
        if self.websocket is not None:
            try:
                await self.websocket.close()
            finally:
                self.websocket = None

    def close(self) -> None:
        """Close the Kraken websocket connection."""
        if self.websocket is not None:
            asyncio.run(self._close_async())

    async def stream_ticks(self) -> AsyncIterator[MarketTick]:
        """Yield a continuous stream of validated pydantic MarketTick objects.

        Connects and subscribes automatically on first call.
        Skips control / heartbeat messages.
        Runs indefinitely until the caller breaks out or the websocket closes.
        """
        if self.websocket is None:
            await self._connect_async()
            await self._subscribe_async()

        while True:
            assert self.websocket is not None
            raw = await asyncio.wait_for(self.websocket.recv(), timeout=15)
            parsed = self.parse_message(json.loads(raw))
            if parsed is not None:
                assert parsed.timestamp is not None
                yield MarketTick(
                    timestamp=parsed.timestamp,
                    symbol=parsed.symbol,
                    price=parsed.price,
                    source="Kraken",
                    schema_version=1,
                )
