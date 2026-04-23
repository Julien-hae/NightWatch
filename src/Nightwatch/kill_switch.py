"""Kill switch — global emergency stop for trading activity."""

import logging

from Nightwatch.metrics import NightwatchMetrics
from Nightwatch.models.bot_control_event import BotControlEvent

LOGGER = logging.getLogger(__name__)


class KillSwitch:
    """Holds the current trading-enabled state, updated by BotControlEvents."""

    def __init__(self, metrics: NightwatchMetrics | None = None) -> None:
        """Initialize with trading enabled by default."""
        self.trading_enabled: bool = True
        self._metrics = metrics

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
