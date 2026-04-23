"""Kill switch — global emergency stop for trading activity."""

import logging
from dataclasses import dataclass

from Nightwatch.models.bot_control_event import BotControlEvent

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class KillSwitch:
    """Holds the current trading-enabled state, updated by BotControlEvents."""

    trading_enabled: bool = True

    def apply(self, event: BotControlEvent) -> None:
        """Update state from a BotControlEvent. NOT thread-safe; must be called from the asyncio event loop."""
        self.trading_enabled = not event.kill
        LOGGER.info(
            "Kill switch updated: trading_enabled=%s reason=%s",
            self.trading_enabled,
            event.reason,
        )
