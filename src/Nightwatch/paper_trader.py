"""Paper trading pipeline: turn approved signals into orders, fills and portfolio updates."""

import json
import logging
from decimal import Decimal

from Nightwatch.metrics import NightwatchMetrics
from Nightwatch.models.fill import Fill
from Nightwatch.models.order import Order
from Nightwatch.models.order_factory import OrderFactoryConfig, SignalDeduplicator, create_order_from_signal
from Nightwatch.models.paper_execution import PercentageFeeModel, paper_execute
from Nightwatch.models.portfolio import Portfolio
from Nightwatch.models.signal import Signal

LOGGER = logging.getLogger(__name__)


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
    ) -> None:
        """Initialise the paper trader.

        Args:
            portfolio: Portfolio whose cash, positions and last prices are mutated.
            order_factory_config: Sizing configuration used to build orders.
            fee_model: Fee model used by the paper executor.
            metrics: Optional metrics instance for orders/fills/equity counters.
            deduplicator: Optional deduplicator. When omitted, a fresh one is
                created and wired to the duplicates counter from ``metrics``.
        """
        self._portfolio = portfolio
        self._order_factory_config = order_factory_config
        self._fee_model = fee_model
        self._metrics = metrics
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
