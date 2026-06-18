"""Repository interfaces and in-memory implementations for paper trading."""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Protocol

from Nightwatch.models.fill import Fill
from Nightwatch.models.order import Order
from Nightwatch.models.portfolio import Portfolio
from Nightwatch.models.signal import Signal

if TYPE_CHECKING:
    from Nightwatch.bootstrap import PersistenceContext


class OrderCreateResult(str, Enum):
    """Result of trying to create an order in an idempotent repository."""

    CREATED = "CREATED"
    ALREADY_EXISTS = "ALREADY_EXISTS"


class AsyncSignalRepo(Protocol):
    """Async persistence port for signals."""

    async def save(self, signal: Signal) -> None:
        """Persist a signal (idempotent upsert)."""


class AsyncPositionRepo(Protocol):
    """Async persistence port for positions."""

    async def get_all(self) -> dict[str, Decimal]:
        """Return all positions as a mapping of symbol to quantity."""

    async def upsert(self, symbol: str, qty: Decimal) -> None:
        """Insert or replace the quantity for *symbol*."""


class AsyncPortfolioStateRepo(Protocol):
    """Async persistence port for portfolio state (cash balance)."""

    async def get_cash(self) -> Decimal:
        """Return current cash balance, or zero if not found."""

    async def save_cash(self, cash: Decimal) -> None:
        """Persist or update cash balance."""


class AsyncEquitySnapshotRepo(Protocol):
    """Async persistence port for equity snapshots."""

    async def insert(self, equity: Decimal, cash: Decimal) -> None:
        """Append an equity snapshot row."""


class AsyncProcessingCursorRepo(Protocol):
    """Async persistence port for the processing cursor (last processed signal id)."""

    async def get_last_signal_id(self) -> uuid.UUID | None:
        """Return the id of the last successfully processed signal, or None."""

    async def save_last_signal_id(self, signal_id: uuid.UUID) -> None:
        """Persist the id of the last successfully processed signal."""


class AsyncTradeWriter(Protocol):
    """Async port for atomically persisting an order/fill/portfolio update."""

    async def write_trade(
        self,
        order: Order,
        fill: Fill,
        *,
        position_qty: Decimal,
        cash: Decimal,
        equity: Decimal,
    ) -> object:
        """Persist the trade in a single DB transaction."""


@dataclass
class PaperTraderRepos:
    """Bundle of persistence ports consumed by :class:`PaperTrader`."""

    signal: AsyncSignalRepo | None = None
    position: AsyncPositionRepo | None = None
    portfolio_state: AsyncPortfolioStateRepo | None = None
    equity_snapshot: AsyncEquitySnapshotRepo | None = None
    processing_cursor: AsyncProcessingCursorRepo | None = None
    trade_writer: AsyncTradeWriter | None = None

    @classmethod
    def from_context(cls, ctx: "PersistenceContext") -> "PaperTraderRepos":
        """Build a fully-populated bundle from a :class:`PersistenceContext`."""
        return cls(
            signal=ctx.signal_repo,
            position=ctx.position_repo,
            portfolio_state=ctx.portfolio_state_repo,
            equity_snapshot=ctx.equity_snapshot_repo,
            processing_cursor=ctx.processing_cursor_repo,
            trade_writer=ctx.trade_writer,
        )


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
