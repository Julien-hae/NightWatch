"""Abstract base class for risk rules."""

from abc import ABC, abstractmethod

from Nightwatch.models.risk_decision import RiskDecision
from Nightwatch.models.signal import Signal


class RiskRule(ABC):
    """A single risk check applied to a trading signal."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name of this rule (used in RiskDecision.rule)."""

    @abstractmethod
    def evaluate(self, signal: Signal) -> RiskDecision | None:
        """Evaluate the signal.

        Returns:
            None if the signal passes this rule (no objection).
            A RiskDecision(allowed=False, ...) if the signal is rejected.
        """

    def confirm(self, signal: Signal) -> None:
        """Confirm that the signal has been allowed by all rules. Used to update internal state after a signal is accepted."""
