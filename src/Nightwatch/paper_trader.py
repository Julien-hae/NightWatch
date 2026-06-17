"""Paper trading pipeline: turn approved signals into orders, fills and portfolio updates."""

import json
import logging
from decimal import Decimal
from typing import Protocol

from Nightwatch.metrics import NightwatchMetrics
from Nightwatch.models.fill import Fill
from Nightwatch.models.order import Order
from Nightwatch.models.order_factory import OrderFactoryConfig, SignalDeduplicator, create_order_from_signal
from Nightwatch.models.paper_execution import PercentageFeeModel, paper_execute
from Nightwatch.models.portfolio import Portfolio
from Nightwatch.models.signal import Signal

LOGGER = logging.getLogger(__name__)


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


class PaperTrader:
    """Wire approved signals through the paper trading pipeline.

    Builds an order from the signal, executes it immediately against the latest
    tick price via :func:`paper_execute`, applies the resulting fill to the
    portfolio and updates Prometheus metrics. Duplicate signals (already
    processed) are ignored.
    """

    def __init__(
        self,
        portfolio: Portfolio,
        order_factory_config: OrderFactoryConfig,
        fee_model: PercentageFeeModel,
        metrics: NightwatchMetrics | None = None,
        deduplicator: SignalDeduplicator | None = None,
        position_repo: AsyncPositionRepo | None = None,
        portfolio_state_repo: AsyncPortfolioStateRepo | None = None,
        equity_snapshot_repo: AsyncEquitySnapshotRepo | None = None,
    ) -> None:
        """Initialise the paper trader.

        Args:
            portfolio: Portfolio whose cash, positions and last prices are mutated.
            order_factory_config: Sizing configuration used to build orders.
            fee_model: Fee model used by the paper executor.
            metrics: Optional metrics instance for orders/fills/equity counters.
            deduplicator: Optional deduplicator. When omitted, a fresh one is
                created and wired to the duplicates counter from ``metrics``.
            position_repo: Optional async position repository for persisting position state.
            portfolio_state_repo: Optional async portfolio state repo for persisting cash.
            equity_snapshot_repo: Optional async equity snapshot repo for persisting snapshots.
        """
        self._portfolio = portfolio
        self._order_factory_config = order_factory_config
        self._fee_model = fee_model
        self._metrics = metrics
        self._position_repo = position_repo
        self._portfolio_state_repo = portfolio_state_repo
        self._equity_snapshot_repo = equity_snapshot_repo
        if deduplicator is None:
            duplicates_counter = metrics.signals_duplicates_total if metrics is not None else None
            deduplicator = SignalDeduplicator(duplicates_counter=duplicates_counter)
        self._deduplicator = deduplicator
        self._refresh_portfolio_metrics()

    @property
    def portfolio(self) -> Portfolio:
        """Return the portfolio managed by this paper trader."""
        return self._portfolio

    def observe_price(self, symbol: str, price: Decimal) -> None:
        """Record the latest market price for a symbol and refresh equity metrics."""
        self._portfolio.last_prices[symbol] = price
        if self._metrics is not None:
            self._metrics.equity.set(float(self._portfolio.equity()))

    def process_signal(self, signal: Signal) -> Fill | None:
        """Process an approved signal end-to-end and return the resulting fill, if any.

        Args:
            signal: An approved trading signal.

        Returns:
            The :class:`Fill` produced by the paper executor, or ``None`` if no
            order was created (duplicate signal, or SELL with no held position).
        """
        order = create_order_from_signal(
            signal,
            self._portfolio,
            self._order_factory_config,
            self._deduplicator,
        )
        if order is None:
            return None
        if self._metrics is not None:
            self._metrics.orders_created_total.labels(symbol=order.symbol, side=order.side.value).inc()

        last_price = self._portfolio.last_price(order.symbol)
        assert last_price is not None  # guaranteed by create_order_from_signal
        self._log_order_created(order, last_price)

        fill = paper_execute(order, last_price, self._fee_model)
        self._portfolio.apply_fill(fill)
        if self._metrics is not None:
            self._metrics.orders_filled_total.labels(symbol=order.symbol, side=order.side.value).inc()
            self._metrics.fees_paid_total.labels(symbol=order.symbol).inc(float(fill.fee))
        self._refresh_portfolio_metrics()
        self._log_order_filled(order, fill)
        return fill

    def _log_order_created(self, order: Order, price: Decimal) -> None:
        LOGGER.info(
            json.dumps(
                {
                    "event": "order_created",
                    "order_id": str(order.order_id),
                    "signal_id": str(order.signal_id),
                    "symbol": order.symbol,
                    "side": order.side.value,
                    "qty": str(order.qty),
                    "price": str(price),
                },
                default=str,
            )
        )

    def _log_order_filled(self, order: Order, fill: Fill) -> None:
        LOGGER.info(
            json.dumps(
                {
                    "event": "order_filled",
                    "order_id": str(order.order_id),
                    "fill_id": str(fill.fill_id),
                    "signal_id": str(order.signal_id),
                    "symbol": fill.symbol,
                    "side": fill.side.value,
                    "qty": str(fill.qty),
                    "price": str(fill.price),
                    "fee": str(fill.fee),
                    "cash": str(self._portfolio.cash),
                    "pos": str(self._portfolio.position_qty(fill.symbol)),
                    "equity": str(self._portfolio.equity()),
                },
                default=str,
            )
        )

    def _refresh_portfolio_metrics(self) -> None:
        if self._metrics is None:
            return
        self._metrics.cash_balance.set(float(self._portfolio.cash))
        for symbol, qty in self._portfolio.positions.items():
            self._metrics.position_qty.labels(symbol=symbol).set(float(qty))
            last_price = self._portfolio.last_price(symbol)
            if last_price is not None:
                self._metrics.equity_per_symbol.labels(symbol=symbol).set(float(qty * last_price))
        self._metrics.equity.set(float(self._portfolio.equity()))

    async def rehydrate(self) -> None:
        """Load persisted cash and positions from the database and restore portfolio state.

        Should be called once at startup to resume from the last known state.
        Has no effect when either repository is absent.
        """
        if self._portfolio_state_repo is not None:
            self._portfolio.cash = await self._portfolio_state_repo.get_cash()

        if self._position_repo is not None:
            positions = await self._position_repo.get_all()
            self._portfolio.positions = positions

        LOGGER.info(
            json.dumps(
                {
                    "event": "rehydrate",
                    "cash": float(self._portfolio.cash),
                    "positions": {s: float(q) for s, q in self._portfolio.positions.items()},
                },
                default=str,
            )
        )

    async def persist_fill_state(self, fill: Fill) -> None:
        """Persist position, cash, and equity snapshot after a fill.

        Args:
            fill: The fill that was just applied to the portfolio.
        """
        if self._position_repo is not None:
            qty = self._portfolio.position_qty(fill.symbol)
            await self._position_repo.upsert(fill.symbol, qty)

        if self._portfolio_state_repo is not None:
            await self._portfolio_state_repo.save_cash(self._portfolio.cash)

        if self._equity_snapshot_repo is not None:
            equity = self._portfolio.equity()
            await self._equity_snapshot_repo.insert(equity, self._portfolio.cash)
