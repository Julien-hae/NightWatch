"""Repository interfaces and in-memory implementations for paper trading."""

from __future__ import annotations

import copy
from decimal import Decimal
from enum import Enum
from typing import Protocol

from Nightwatch.models.fill import Fill
from Nightwatch.models.order import Order
from Nightwatch.models.portfolio import Portfolio
from Nightwatch.models.signal import Signal


class OrderCreateResult(str, Enum):
    """Result of trying to create an order in an idempotent repository."""

    CREATED = "CREATED"
    ALREADY_EXISTS = "ALREADY_EXISTS"


class SignalRepo(Protocol):
    """Persistence port for signals."""

    def save(self, signal: Signal) -> None:
        """Persist a signal."""


class OrderRepo(Protocol):
    """Persistence port for orders."""

    def create(self, order: Order) -> OrderCreateResult:
        """Create an order once, or return already-exists on duplicate idempotency key."""


class FillRepo(Protocol):
    """Persistence port for fills."""

    def append(self, fill: Fill) -> None:
        """Append a fill."""


class Position(Protocol):
    """Minimal position shape used by the in-memory position repository."""

    symbol: str
    qty: Decimal


class PositionRepo(Protocol):
    """Persistence port for positions."""

    def get(self, symbol: str) -> Decimal:
        """Return current quantity for *symbol* or zero if absent."""

    def upsert(self, position: Position) -> None:
        """Insert or replace the quantity for *position.symbol*."""


class PortfolioRepo(Protocol):
    """Persistence port for full portfolio state snapshots."""

    def load_state(self) -> Portfolio:
        """Load current portfolio state."""

    def save_state(self, portfolio: Portfolio) -> None:
        """Persist full portfolio state."""


class InMemorySignalRepo:
    """In-memory signal store keyed by signal uid."""

    def __init__(self) -> None:
        """Initialize an empty signal store."""
        self._signals: dict[str, Signal] = {}

    def save(self, signal: Signal) -> None:
        """Persist *signal* by its uid, replacing any existing value."""
        self._signals[str(signal.uid)] = signal


class InMemoryOrderRepo:
    """In-memory order store with idempotent create semantics.

    The idempotency key is derived from ``order.signal_id`` so one signal
    can create at most one stored order.
    """

    def __init__(self) -> None:
        """Initialize an empty idempotency-keyed order store."""
        self._orders_by_idempotency: dict[str, Order] = {}

    def create(self, order: Order) -> OrderCreateResult:
        """Store *order* once, returning ``ALREADY_EXISTS`` on duplicate key."""
        key = str(order.signal_id)
        if key in self._orders_by_idempotency:
            return OrderCreateResult.ALREADY_EXISTS
        self._orders_by_idempotency[key] = order
        return OrderCreateResult.CREATED


class InMemoryFillRepo:
    """In-memory append-only fill store."""

    def __init__(self) -> None:
        """Initialize an empty fill list."""
        self._fills: list[Fill] = []

    def append(self, fill: Fill) -> None:
        """Append *fill* to the in-memory journal."""
        self._fills.append(fill)


class InMemoryPositionRepo:
    """In-memory symbol -> quantity position store."""

    def __init__(self) -> None:
        """Initialize an empty position map."""
        self._positions: dict[str, Decimal] = {}

    def get(self, symbol: str) -> Decimal:
        """Return quantity for *symbol*, or zero when absent."""
        return self._positions.get(symbol, Decimal("0"))

    def upsert(self, position: Position) -> None:
        """Insert or replace quantity for ``position.symbol``."""
        self._positions[position.symbol] = position.qty


class InMemoryPortfolioRepo:
    """In-memory portfolio snapshot store."""

    def __init__(self, initial_state: Portfolio | None = None) -> None:
        """Initialize snapshot storage with an optional initial state."""
        self._state = copy.deepcopy(initial_state) if initial_state is not None else Portfolio()

    def load_state(self) -> Portfolio:
        """Return a defensive copy of the currently saved portfolio state."""
        return copy.deepcopy(self._state)

    def save_state(self, portfolio: Portfolio) -> None:
        """Persist a defensive copy of *portfolio*."""
        self._state = copy.deepcopy(portfolio)
