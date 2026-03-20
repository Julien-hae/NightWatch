"""Module to define the StrategyDecision dataclass, which represents the decision made by a trading strategy."""

from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from Nightwatch.models.signal import Side


@dataclass(frozen=True)
class StrategyDecision:
    """A dataclass to represent the decision made by a trading strategy."""

    side: Side
    strength: float
    rationale: dict[str, float | Decimal]

    def __post_init__(self) -> None:
        """Convert the rationale dictionary to an immutable MappingProxyType after initialization."""
        object.__setattr__(self, "rationale", MappingProxyType(self.rationale))
