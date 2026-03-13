# mypy: disable-error-code="import-untyped"
"""Unit tests for utility functions in Nightwatch."""

import unittest

from Nightwatch.common.utils import normalize_symbol


class TestUtils(unittest.TestCase):
    """Test suite for utility functions."""

    def test_normalize_symbol(self) -> None:
        """Test that normalize_symbol correctly normalizes various symbol formats."""
        test_cases = [
            ("BTC/USD", "BTCUSD"),
            ("ETH-USD", "ETHUSD"),
            ("eth-usd", "ETHUSD"),
            ("XRP:USD", "XRPUSD"),
            ("LTC_USD", "LTCUSD"),
            ("ADAUSD", "ADAUSD"),
            ("", ""),
            (" ", ""),
        ]
        for input_symbol, expected in test_cases:
            with self.subTest(input_symbol=input_symbol):
                result = normalize_symbol(input_symbol)
                self.assertEqual(result, expected)
