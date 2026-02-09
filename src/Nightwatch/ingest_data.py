"""Module for ingesting live stock data from Alpaca API."""

import os
import queue
import threading
from typing import Optional

from alpaca.data.live.stock import StockDataStream
from alpaca.data.models.quotes import Quote
from dotenv import load_dotenv


class AlpacaDataIngestor:
    """Class to ingest live stock data from Alpaca API."""

    def __init__(self) -> None:
        """Initialize the AlpacaDataIngestor with API credentials."""
        load_dotenv("credentials.env")

        api_key = os.getenv("ALPACA_API_KEY")
        if api_key is None:
            raise ValueError("ALPACA_API_KEY not found in environment")
        self.api_key: str = api_key

        api_secret = os.getenv("ALPACA_API_SECRET")
        if api_secret is None:
            raise ValueError("ALPACA_API_SECRET not found in environment")
        self.api_secret: str = api_secret

    def get_live_data(self, symbol: str, timeout: int = 30) -> Optional[Quote]:
        """Fetch live stock data for a given symbol.

        Args:
            symbol: Stock symbol to fetch data for (e.g., "AAPL")
            timeout: Maximum time to wait for data in seconds

        Returns:
            The quote data, or None if no data received
        """
        data_queue: queue.Queue[Quote] = queue.Queue()
        stock_data_stream_client = StockDataStream(self.api_key, self.api_secret, url_override=None)

        async def stock_data_stream_handler(data: Quote) -> None:
            """Handler to collect quote data."""
            data_queue.put(data)
            stock_data_stream_client.stop()

        stock_data_stream_client.subscribe_quotes(stock_data_stream_handler, symbol)  # type: ignore[arg-type]

        def run_stream() -> None:
            stock_data_stream_client.run()

        stream_thread = threading.Thread(target=run_stream, daemon=True)
        stream_thread.start()

        try:
            data = data_queue.get(timeout=timeout)
            return data
        except queue.Empty:
            stock_data_stream_client.stop()
            return None
