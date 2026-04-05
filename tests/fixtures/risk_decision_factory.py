"""Factory functions to create test instances of the RiskDecision model."""

import uuid

from Nightwatch.models.risk_decision import RiskDecision


def make_risk_decision(
    symbol: str = "BTC/USD",
    allowed: bool = True,
    reason: str | None = None,
    rule: str | None = None,
    signal_id: uuid.UUID | None = None,
) -> RiskDecision:
    """Helper function to create a RiskDecision with default values for testing."""
    return RiskDecision(
        symbol=symbol,
        allowed=allowed,
        reason=reason,
        rule=rule,
        signal_id=signal_id or uuid.uuid4(),
    )
