"""Re-exports ControlEventSubscriber from the messaging package (kept for backward compatibility)."""

from Nightwatch.messaging.control_event_subscriber import DEFAULT_DURABLE_NAME, ControlEventSubscriber

__all__ = ["DEFAULT_DURABLE_NAME", "ControlEventSubscriber"]
