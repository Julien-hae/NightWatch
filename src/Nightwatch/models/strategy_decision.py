"""Module to define the StrategyDecision dataclass, which represents the decision made by a trading strategy."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Union

from Nightwatch.models.signal import Side


@dataclass(frozen=True)
class StrategyDecision:
    """A dataclass to represent the decision made by a trading strategy."""

    side: Side
    strength: float
    rationale: dict[str, Union[float, Decimal]]
