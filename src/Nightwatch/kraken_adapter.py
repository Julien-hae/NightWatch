"""KrakenAdapter module."""

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, Optional

import pytz  # type: ignore[import-untyped]
from websockets import connect
from websockets.asyncio.client import ClientConnection

from Nightwatch.exchange_market_adapter import ExchangeMarketAdapter, MarketTick


class KrakenAdapter(ExchangeMarketAdapter):
    """Adapter to ingest live stock data from the Kraken API."""

    def __init__(self) -> None:
        """Initialize the KrakenAdapter class."""
        super().__init__()
        self.websocket: Optional[ClientConnection] = None
        self.uri = "wss://ws.kraken.com/v2"
        self.symbol = "BTC/USD"

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
        """Parse a message received from the websocket and return a MarketTick object."""
        if isinstance(message, dict) and message.get("data", None) is not None:
            if message.get("channel", "") == "ticker":
                naive_dt = datetime.fromisoformat(message["data"][0]["timestamp"].replace("Z", "+00:00"))
                aware_utc_dt = naive_dt.replace(tzinfo=pytz.utc)
                return MarketTick(
                    symbol=message["data"][0].get("symbol", ""), price=float(message["data"][0].get("last", 0)), timestamp=aware_utc_dt
                )
        return None
