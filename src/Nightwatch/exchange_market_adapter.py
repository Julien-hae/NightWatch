"""Module for ingesting live stock data from any API."""

from typing import Any, Dict, Optional


class MarketTick:
    """Class to represent a market tick."""

    def __init__(self, symbol: str, price: float, timestamp: Optional[Any]) -> None:
        """Initialize the MarketTick class."""
        self.symbol = symbol
        self.price = price
        self.timestamp = timestamp


class ExchangeMarketAdapter:
    """Class to ingest live stock data from any API."""

    def __init__(self) -> None:
        """Initialize the ExchangeMarketAdapter class."""
        pass

    def connect(self) -> None:
        """Connect to a websocket to receive live stock data."""
        raise NotImplementedError("Method not implemented yet.")

    def subscribe(self) -> None:
        """Subscribe to a symbol to receive live stock data."""
        raise NotImplementedError("Method not implemented yet.")

    def parse_message(self, message: Optional[Dict[str, Any]]) -> Optional[MarketTick]:
        """Parse a message received from the websocket and return a MarketTick object."""
        _ = message
        return MarketTick(symbol="", price=0.0, timestamp=None)
