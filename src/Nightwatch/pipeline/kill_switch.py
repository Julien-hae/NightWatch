"""Kill switch — global emergency stop for trading activity."""

import logging

from Nightwatch.metrics.metrics import NightwatchMetrics
from Nightwatch.models.bot_control_event import BotControlEvent

LOGGER = logging.getLogger(__name__)


class KillSwitch:
    """Holds the current trading-enabled state, updated by BotControlEvents.

    The *ready* flag gates signal processing on startup.  When ``ready=False``
    the ``StrategyRunner`` must suppress all signals until the JetStream
    backlog has been drained and the kill-switch state restored.  Call
    ``mark_ready()`` once the backlog drain is complete.
    """

    def __init__(self, metrics: NightwatchMetrics | None = None, *, ready: bool = True) -> None:
        """Initialize with trading enabled by default.

        Args:
            metrics: Optional Prometheus metrics instance.
            ready: If *False*, signals are suppressed until ``mark_ready()``
                is called.  Defaults to *True* for backward compatibility.
        """
        self.trading_enabled: bool = True
        self._ready: bool = ready
        self._metrics = metrics

    @property
    def ready(self) -> bool:
        """Return whether the kill-switch state has been restored from the backlog."""
        return self._ready

    def mark_ready(self) -> None:
        """Mark the kill switch as ready after the JetStream backlog has been drained."""
        self._ready = True
        LOGGER.info("Kill switch marked ready: trading_enabled=%s", self.trading_enabled)

    def apply(self, event: BotControlEvent) -> None:
        """Update state from a BotControlEvent. NOT thread-safe; must be called from the asyncio event loop."""
        if self.trading_enabled != (not event.kill):
            if self._metrics is not None:
                self._metrics.kill_switch_toggles_total.inc()
        self.trading_enabled = not event.kill
        LOGGER.info(
            "Kill switch updated: trading_enabled=%s reason=%s timestamp=%s",
            self.trading_enabled,
            event.reason,
            event.timestamp,
        )
