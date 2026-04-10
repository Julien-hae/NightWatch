"""Re-exports NatsConnector from the messaging package (kept for backward compatibility)."""

from Nightwatch.messaging.nats_connection import NatsConnector

__all__ = ["NatsConnector"]
