import os
import unittest

from dotenv import load_dotenv

from Nightwatch.ingest_data import AlpacaDataIngestor

load_dotenv("credentials.env")


class TestIngestData(unittest.TestCase):
    """Unit tests for the AlpacaDataIngestor class."""

    def test_alpaca_credentials(self) -> None:
        """Test that Alpaca API credentials are loaded from environment variables."""
        api_key = os.getenv("ALPACA_API_KEY")
        api_secret = os.getenv("ALPACA_API_SECRET")
        self.assertIsNotNone(api_key, "ALPACA_API_KEY not found in environment")
        self.assertIsNotNone(api_secret, "ALPACA_API_SECRET not found in environment")

    def test_get_live_data(self) -> None:
        """Test that we can initialize the Alpaca data stream client."""
        ingestor = AlpacaDataIngestor()
        data = ingestor.get_live_data(symbol="AAPL")
        self.assertIsNotNone(data)
        if data is not None:
            self.assertEqual(data.symbol, "AAPL")
