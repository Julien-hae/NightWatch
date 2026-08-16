"""Deterministic JSON capture of signals, orders and fills for regression testing.

Wire a :class:`PipelineCapture` instance into ``StrategyRunner`` and ``PaperTrader`` to
observe every approved signal, created order and executed fill as they happen. Only
business fields are recorded — UUIDs and wall-clock timestamps are omitted rather than
captured, so replaying the same tick file twice produces byte-identical output.
"""

import json

from Nightwatch.models.fill import Fill
from Nightwatch.models.order import Order
from Nightwatch.models.signal import Signal


class PipelineCapture:
    """Collects Signal/Order/Fill events into a stable, JSON-serializable list."""

    def __init__(self) -> None:
        """Initialise an empty capture with no recorded events."""
        self._events: list[dict[str, object]] = []

    def on_signal(self, signal: Signal) -> None:
        """Record an approved signal."""
        self._events.append(
            {
                "type": "signal",
                "symbol": signal.symbol,
                "side": signal.side.value,
                "strategy": signal.strategy,
                "strength": signal.strength,
                "delta_pct": signal.rationale.get("delta_pct"),
            }
        )

    def on_order(self, order: Order) -> None:
        """Record a created order."""
        self._events.append(
            {
                "type": "order",
                "symbol": order.symbol,
                "side": order.side.value,
                "qty": str(order.qty),
                "status": order.status.value,
            }
        )

    def on_fill(self, fill: Fill) -> None:
        """Record an executed fill."""
        self._events.append(
            {
                "type": "fill",
                "symbol": fill.symbol,
                "side": fill.side.value,
                "qty": str(fill.qty),
                "price": str(fill.price),
                "fee": str(fill.fee),
            }
        )

    def events(self) -> list[dict[str, object]]:
        """Return a shallow copy of the captured events, in emission order."""
        return list(self._events)

    def write(self, path: str) -> None:
        """Write all captured events as a JSON array to *path*."""
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self._events, fh, indent=2, default=str)
            fh.write("\n")
