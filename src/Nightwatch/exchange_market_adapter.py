"""Module for ingesting live stock data from any API."""

from typing import Any, Dict, Optional

from Nightwatch.models.market_tick import MarketTick


class ExchangeMarketAdapter:
    """Class to ingest live stock data from any API."""

    def __init__(self) -> None:
        """Initialize the ExchangeMarketAdapter class."""

    def connect(self) -> None:
        """Connect to a websocket to receive live stock data."""
        raise NotImplementedError("Method not implemented yet.")

    def subscribe(self) -> None:
        """Subscribe to a symbol to receive live stock data."""
        raise NotImplementedError("Method not implemented yet.")

    def close(self) -> None:
        """Close the websocket connection."""
        raise NotImplementedError("Method not implemented yet.")

    def parse_message(self, message: Optional[Dict[str, Any]]) -> Optional[MarketTick]:
        """Parse a message received from the websocket and return a MarketTick object."""
        raise NotImplementedError("Method not implemented yet.")
