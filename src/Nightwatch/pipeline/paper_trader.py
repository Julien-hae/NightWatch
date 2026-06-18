"""Paper trading pipeline: turn approved signals into orders, fills and portfolio updates."""

import json
import logging
import time
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from Nightwatch.db.repositories import PaperTraderRepos
from Nightwatch.metrics import NightwatchMetrics
from Nightwatch.models.fill import Fill
from Nightwatch.models.order import Order
from Nightwatch.models.order_factory import OrderFactoryConfig, SignalDeduplicator, create_order_from_signal
from Nightwatch.models.paper_execution import PercentageFeeModel, paper_execute
from Nightwatch.models.portfolio import Portfolio
from Nightwatch.models.signal import Signal

if TYPE_CHECKING:
    from Nightwatch.db.bootstrap import PersistenceContext

LOGGER = logging.getLogger(__name__)


class PaperTrader:
    """Wire approved signals through the paper trading pipeline.

    Builds an order from each approved signal, executes it against the latest
    tick price via :func:`paper_execute`, applies the fill to the portfolio,
    and (when persistence repos are wired via :class:`PaperTraderRepos`)
    durably stores the trade via :meth:`process_and_persist` / :meth:`rehydrate`.
    Duplicate signals are deduplicated by ``signal.uid``.
    """

    def __init__(
        self,
        portfolio: Portfolio,
        order_factory_config: OrderFactoryConfig,
        fee_model: PercentageFeeModel,
        metrics: NightwatchMetrics | None = None,
        deduplicator: SignalDeduplicator | None = None,
        repos: PaperTraderRepos | None = None,
    ) -> None:
        """Initialise the paper trader.

        Args:
            portfolio: Portfolio whose cash, positions and last prices are mutated.
            order_factory_config: Sizing configuration used to build orders.
            fee_model: Fee model used by the paper executor.
            metrics: Optional metrics instance for orders/fills/equity counters.
            deduplicator: Optional deduplicator. When omitted, a fresh one is
                created and wired to the duplicates counter from ``metrics``.
            repos: Optional bundle of persistence ports. When omitted, persistence
                is skipped; see :meth:`attach_repos` to wire one later.
        """
        self._portfolio = portfolio
        self._order_factory_config = order_factory_config
        self._fee_model = fee_model
        self._metrics = metrics
        self._repos = repos or PaperTraderRepos()
        self._last_processed_signal_id: uuid.UUID | None = None
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

        last_price = self._portfolio.last_price(order.symbol)
        assert last_price is not None  # guaranteed by create_order_from_signal
        self._log_order_created(order, last_price)

        fill = paper_execute(order, last_price, self._fee_model)
        self._portfolio.apply_fill(fill)
        if self._metrics is not None:
            self._metrics.orders_created_total.labels(symbol=order.symbol, side=order.side.value).inc()
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
        """Load persisted cash, positions and processing cursor from the database.

        Should be called once at startup to resume from the last known state.
        Records elapsed time on ``metrics.rehydration_duration_seconds`` and emits
        a ``"Rehydrated portfolio"`` log line summarising restored state. Has no
        effect when the corresponding repository is absent.
        """
        start = time.perf_counter()
        if self._repos.portfolio_state is not None:
            self._portfolio.cash = await self._repos.portfolio_state.get_cash()

        if self._repos.position is not None:
            positions = await self._repos.position.get_all()
            self._portfolio.positions = positions

        if self._repos.processing_cursor is not None:
            self._last_processed_signal_id = await self._repos.processing_cursor.get_last_signal_id()

        elapsed = time.perf_counter() - start
        if self._metrics is not None:
            self._metrics.rehydration_duration_seconds.observe(elapsed)
        self._refresh_portfolio_metrics()

        LOGGER.info(
            "Rehydrated portfolio %s",
            json.dumps(
                {
                    "cash": float(self._portfolio.cash),
                    "positions": {s: float(q) for s, q in self._portfolio.positions.items()},
                    "last_signal_id": str(self._last_processed_signal_id) if self._last_processed_signal_id else None,
                    "duration_seconds": elapsed,
                },
                default=str,
            ),
        )

    @property
    def last_processed_signal_id(self) -> uuid.UUID | None:
        """Return the last processed signal id loaded during ``rehydrate``."""
        return self._last_processed_signal_id

    async def persist_fill_state(self, fill: Fill, signal_id: uuid.UUID | None = None) -> None:
        """Persist position, cash, equity snapshot and processing cursor after a fill.

        Args:
            fill: The fill that was just applied to the portfolio.
            signal_id: When provided and a cursor repo is wired, persisted as the
                latest processed signal id so a restart can resume safely.
        """
        if self._repos.position is not None:
            qty = self._portfolio.position_qty(fill.symbol)
            await self._repos.position.upsert(fill.symbol, qty)

        if self._repos.portfolio_state is not None:
            await self._repos.portfolio_state.save_cash(self._portfolio.cash)

        if self._repos.equity_snapshot is not None:
            equity = self._portfolio.equity()
            await self._repos.equity_snapshot.insert(equity, self._portfolio.cash)

        if signal_id is not None and self._repos.processing_cursor is not None:
            await self._repos.processing_cursor.save_last_signal_id(signal_id)
            self._last_processed_signal_id = signal_id

    async def process_and_persist(self, signal: Signal) -> Fill | None:
        """Process *signal* end-to-end and persist the trade durably.

        When a ``trade_writer`` is wired, the order, fill, updated position,
        cash balance, processing cursor and equity snapshot are written in a
        single DB transaction that is idempotent on ``signal.uid``. When no
        writer is wired, falls back to :meth:`persist_fill_state`. A signal
        repository, when wired, is updated first so the signal is durably
        recorded even when the trade is a no-op (duplicate or SELL with no
        position).

        Args:
            signal: An approved trading signal.

        Returns:
            The :class:`Fill` produced by the paper executor, or ``None`` when
            no order was created.

        Raises:
            Exception: Re-raises any persistence failure after reverting the
                in-memory portfolio mutation so the in-memory state stays
                consistent with the database.
        """
        if self._repos.signal is not None:
            await self._repos.signal.save(signal)

        order = create_order_from_signal(
            signal,
            self._portfolio,
            self._order_factory_config,
            self._deduplicator,
        )
        if order is None:
            return None

        last_price = self._portfolio.last_price(order.symbol)
        assert last_price is not None  # guaranteed by create_order_from_signal
        self._log_order_created(order, last_price)

        fill = paper_execute(order, last_price, self._fee_model)
        self._portfolio.apply_fill(fill)

        try:
            if self._repos.trade_writer is not None:
                await self._repos.trade_writer.write_trade(
                    order,
                    fill,
                    position_qty=self._portfolio.position_qty(fill.symbol),
                    cash=self._portfolio.cash,
                    equity=self._portfolio.equity(),
                )
                self._last_processed_signal_id = signal.uid
            else:
                await self.persist_fill_state(fill, signal_id=signal.uid)
        except Exception:
            self._portfolio.revert_fill(fill)
            raise

        if self._metrics is not None:
            self._metrics.orders_created_total.labels(symbol=order.symbol, side=order.side.value).inc()
            self._metrics.orders_filled_total.labels(symbol=order.symbol, side=order.side.value).inc()
            self._metrics.fees_paid_total.labels(symbol=order.symbol).inc(float(fill.fee))
        self._refresh_portfolio_metrics()
        self._log_order_filled(order, fill)
        return fill

    def attach_repos(self, ctx: "PersistenceContext") -> None:
        """Replace any unset repo in the bundle with the matching repo from *ctx*."""
        self._repos = PaperTraderRepos(
            signal=self._repos.signal or ctx.signal_repo,
            position=self._repos.position or ctx.position_repo,
            portfolio_state=self._repos.portfolio_state or ctx.portfolio_state_repo,
            equity_snapshot=self._repos.equity_snapshot or ctx.equity_snapshot_repo,
            processing_cursor=self._repos.processing_cursor or ctx.processing_cursor_repo,
            trade_writer=self._repos.trade_writer or ctx.trade_writer,
        )
