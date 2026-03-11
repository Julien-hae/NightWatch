"""Module for ingesting live stock data from any API."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from Nightwatch.models.market_tick import MarketTick


class ExchangeMarketAdapter(ABC):
    """Class to ingest live stock data from any API."""

    @abstractmethod
    async def connect(self) -> None:
        """Connect to a websocket to receive live stock data."""

    @abstractmethod
    async def subscribe(self) -> None:
        """Subscribe to a symbol to receive live stock data."""

    @abstractmethod
    async def close(self) -> None:
        """Close the websocket connection."""

    @abstractmethod
    def parse_message(self, message: Optional[Dict[str, Any]]) -> Optional[MarketTick]:
        """Parse a message received from the websocket and return a MarketTick object."""
