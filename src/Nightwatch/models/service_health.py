"""Defines the ServiceHealth dataclass to track connectivity status of external dependencies."""

from dataclasses import dataclass


@dataclass
class ServiceHealth:
    """Tracks connectivity status of external dependencies."""

    ws_connected: bool = False
    nats_connected: bool = False
