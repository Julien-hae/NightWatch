"""KrakenAdapter module."""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from decimal import Decimal
from typing import Any, AsyncIterator

from websockets import connect
from websockets.asyncio.client import ClientConnection
from websockets.exceptions import WebSocketException

from Nightwatch.adapters.exchange_market_adapter import ExchangeMarketAdapter
from Nightwatch.metrics.metrics import NightwatchMetrics
from Nightwatch.models.market_tick import MarketTick

LOGGER = logging.getLogger(__name__)


class KrakenAdapter(ExchangeMarketAdapter):
    """Adapter to ingest live stock data from the Kraken API."""

    def __init__(self, symbol: str = "BTC/USD", uri: str = "wss://ws.kraken.com/v2", metrics: NightwatchMetrics | None = None) -> None:
        """Initialize the KrakenAdapter class."""
        super().__init__()
        self.websocket: ClientConnection | None = None
        self.uri = uri
        self.symbol = symbol
        self._metrics = metrics

    async def connect(self) -> None:
        """Connect to the Kraken websocket."""
        try:
            self.websocket = await connect(self.uri, max_size=65536)
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

    def parse_message(self, message: dict[str, Any] | None) -> MarketTick | None:
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
            timestamp_str = entry.get("timestamp", "")
            dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            return MarketTick(
                symbol=entry.get("symbol", ""),
                price=Decimal(str(entry.get("last", "0"))),
                timestamp=dt,
                source="Kraken",
                schema_version=1,
            )
        except (KeyError, ValueError, TypeError) as exc:
            if self._metrics is not None:
                self._metrics.parse_errors_total.inc()
            LOGGER.error(
                "Error parsing ticker message field. symbol=%s exc_type=%s exc=%s",
                entry.get("symbol", "<unknown>"),
                type(exc).__name__,
                exc,
            )
        return None

    async def close(self) -> None:
        """Close the Kraken websocket connection, if open."""
        if self.websocket is not None:
            try:
                await self.websocket.close()
            finally:
                self.websocket = None

    async def stream_ticks(
        self,
        backoff_base: int = 2,
        backoff_max: int = 60,
        on_disconnected: Callable[[], Awaitable[None]] | None = None,
    ) -> AsyncIterator[MarketTick]:
        """Yield a continuous stream of validated pydantic MarketTick objects.

        Args:
            backoff_base: Base for the exponential reconnect backoff, in seconds.
            backoff_max: Upper bound on the reconnect backoff delay, in seconds.
            on_disconnected: Optional callback awaited whenever the socket drops,
                before the reconnect backoff sleep. Lets callers (e.g. ``main.py``)
                keep a live health/metrics view of the connection without this
                adapter needing to know about them directly.
        """
        attempt = 0

        while True:
            try:
                if self.websocket is None:
                    await self.connect()
                    await self.subscribe()
                    attempt = 0

                raw = await asyncio.wait_for(self.websocket.recv(), timeout=15)  # type: ignore[union-attr]
                parsed = self.parse_message(json.loads(raw))
                if parsed is not None:
                    if self._metrics is not None:
                        self._metrics.ticks_received_total.labels(symbol=parsed.symbol).inc()
                    yield parsed
            except json.JSONDecodeError as exc:
                if self._metrics is not None:
                    self._metrics.parse_errors_total.inc()
                LOGGER.error("JSON decode error: %s", exc)
            except (ConnectionError, asyncio.TimeoutError, WebSocketException) as exc:
                LOGGER.warning("WebSocket dropped: %s. Retrying with backoff.", exc)
                await self.close()
                if self._metrics is not None:
                    self._metrics.ws_reconnects_total.inc()
                if on_disconnected is not None:
                    await on_disconnected()
                delay = min(backoff_base**attempt, backoff_max)
                await asyncio.sleep(delay)
                attempt += 1
