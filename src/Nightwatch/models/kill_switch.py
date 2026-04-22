"""Kill switch — global emergency stop for trading activity."""

import logging

from pydantic import BaseModel, ConfigDict, Field

from Nightwatch.models.bot_control_event import BotControlEvent

LOGGER = logging.getLogger(__name__)


class KillSwitch(BaseModel):
    """Holds the current trading-enabled state, updated by BotControlEvents."""

    model_config = ConfigDict(validate_assignment=True)
    trading_enabled: bool = Field(default=True)

    def apply(self, event: BotControlEvent) -> None:
        """Update state from a BotControlEvent (kill=True → disabled)."""
        self.trading_enabled = not event.kill
        LOGGER.info(
            "Kill switch updated: trading_enabled=%s reason=%s",
            self.trading_enabled,
            event.reason,
        )
