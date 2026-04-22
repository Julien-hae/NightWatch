"""Kill switch — global emergency stop for trading activity."""

import logging

from Nightwatch.models.bot_control_event import BotControlEvent

LOGGER = logging.getLogger(__name__)


class KillSwitch:
    """Holds the current trading-enabled state, updated by BotControlEvents."""

    def __init__(self, trading_enabled: bool = True) -> None:
        """Initialize the KillSwitch with trading enabled by default."""
        self._trading_enabled = trading_enabled

    @property
    def trading_enabled(self) -> bool:
        """Return True if trading is currently allowed, False otherwise."""
        return self._trading_enabled

    def apply(self, event: BotControlEvent) -> None:
        """Update state from a BotControlEvent (kill=True → disabled)."""
        self._trading_enabled = not event.kill
        LOGGER.info(
            "Kill switch updated: trading_enabled=%s reason=%s",
            self._trading_enabled,
            event.reason,
        )
