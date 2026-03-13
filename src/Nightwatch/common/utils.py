"""Utility functions for Nightwatch, such as symbol normalization for NATS subjects."""

import re


def normalize_symbol(symbol: str) -> str:
    """Normalize a symbol string to be used in NATS subjects (e.g., "BTC/USD" -> "BTCUSD")."""
    return re.sub(r"[^A-Za-z0-9]", "", symbol).upper()
