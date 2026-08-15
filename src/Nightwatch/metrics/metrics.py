"""Implements the NightwatchMetrics dataclass to define Prometheus metrics for the NightWatch service."""

from dataclasses import dataclass, field

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram


@dataclass
class NightwatchMetrics:
    """Prometheus metrics for the NightWatch service.

    Each instance uses its own `CollectorRegistry` so that metrics
    are isolated between tests and do not leak into the global registry.
    """

    registry: CollectorRegistry = field(default_factory=CollectorRegistry)
    ticks_received_total: Counter = field(init=False)
    parse_errors_total: Counter = field(init=False)
    ws_reconnects_total: Counter = field(init=False)
    nats_disconnects_total: Counter = field(init=False)
    nats_reconnects_total: Counter = field(init=False)
    ticks_published_total: Counter = field(init=False)
    ticks_consumed_total: Counter = field(init=False)
    signals_total: Counter = field(init=False)
    strategy_evaluations_total: Counter = field(init=False)
    signals_suppressed_total: Counter = field(init=False)
    risk_evaluations_total: Counter = field(init=False)
    signals_allowed_total: Counter = field(init=False)
    signals_rejected_total: Counter = field(init=False)
    control_events_published_total: Counter = field(init=False)
    control_events_received_total: Counter = field(init=False)
    control_events_dead_lettered_total: Counter = field(init=False)
    kill_switch_toggles_total: Counter = field(init=False)
    signals_duplicates_total: Counter = field(init=False)
    orders_created_total: Counter = field(init=False)
    orders_filled_total: Counter = field(init=False)
    fees_paid_total: Counter = field(init=False)
    cash_balance: Gauge = field(init=False)
    position_qty: Gauge = field(init=False)
    equity: Gauge = field(init=False)
    equity_per_symbol: Gauge = field(init=False)
    db_up: Gauge = field(init=False)
    db_write_errors_total: Counter = field(init=False)
    rehydration_duration_seconds: Histogram = field(init=False)
    replay_ticks_total: Counter = field(init=False)
    replay_duration_seconds: Histogram = field(init=False)

    def __post_init__(self) -> None:
        """Create Prometheus counters bound to the instance registry."""
        self.ticks_received_total = Counter(
            "ticks_received_total",
            "Total number of ticks received from the exchange",
            labelnames=["symbol"],
            registry=self.registry,
        )
        self.ticks_consumed_total = Counter(
            "ticks_consumed_total",
            "Total number of ticks consumed by the service",
            labelnames=["symbol"],
            registry=self.registry,
        )
        self.ticks_published_total = Counter(
            "ticks_published_total",
            "Total number of ticks published to NATS",
            labelnames=["symbol"],
            registry=self.registry,
        )
        self.parse_errors_total = Counter(
            "parse_errors_total",
            "Total number of message parse errors",
            registry=self.registry,
        )
        self.ws_reconnects_total = Counter(
            "ws_reconnects_total",
            "Total number of WebSocket reconnections",
            registry=self.registry,
        )
        self.nats_disconnects_total = Counter(
            "nats_disconnects_total",
            "Total number of NATS disconnections observed, by connection",
            labelnames=["connection"],
            registry=self.registry,
        )
        self.nats_reconnects_total = Counter(
            "nats_reconnects_total",
            "Total number of NATS reconnections observed, by connection",
            labelnames=["connection"],
            registry=self.registry,
        )
        self.signals_total = Counter(
            "signals_total",
            "Total number of trading signals emitted by the strategy",
            labelnames=["symbol", "side", "strategy"],
            registry=self.registry,
        )
        self.risk_evaluations_total = Counter(
            "risk_evaluations_total",
            "Total number of risk evaluations performed",
            labelnames=["symbol"],
            registry=self.registry,
        )
        self.signals_allowed_total = Counter(
            "signals_allowed_total",
            "Total number of signals allowed by the risk engine",
            labelnames=["symbol"],
            registry=self.registry,
        )
        self.signals_rejected_total = Counter(
            "signals_rejected_total",
            "Total number of signals rejected by the risk engine for a given reason",
            labelnames=["symbol", "reason"],
            registry=self.registry,
        )
        self.strategy_evaluations_total = Counter(
            "strategy_evaluations_total",
            "Total number of strategy evaluations performed",
            labelnames=["symbol", "strategy"],
            registry=self.registry,
        )
        self.signals_suppressed_total = Counter(
            "signals_suppressed_total",
            "Total number of signals suppressed due to 'reason'",
            labelnames=["reason"],
            registry=self.registry,
        )
        self.control_events_published_total = Counter(
            "control_events_published_total",
            "Total number of control events published via JetStream",
            registry=self.registry,
        )
        self.control_events_received_total = Counter(
            "control_events_received_total",
            "Total number of control events received by the subscriber",
            registry=self.registry,
        )
        self.control_events_dead_lettered_total = Counter(
            "control_events_dead_lettered_total",
            "Total number of control events dead-lettered after exhausting max delivery attempts",
            registry=self.registry,
        )
        self.kill_switch_toggles_total = Counter(
            "kill_switch_toggles_total",
            "Total number of kill switch toggles",
            registry=self.registry,
        )
        self.signals_duplicates_total = Counter(
            "signals_duplicates_total",
            "Total number of duplicate signals ignored by the order factory",
            registry=self.registry,
        )
        self.orders_created_total = Counter(
            "orders_created_total",
            "Total number of orders created from approved signals",
            labelnames=["symbol", "side"],
            registry=self.registry,
        )
        self.orders_filled_total = Counter(
            "orders_filled_total",
            "Total number of orders filled by the paper executor",
            labelnames=["symbol", "side"],
            registry=self.registry,
        )
        self.fees_paid_total = Counter(
            "fees_paid_total",
            "Cumulative fees paid by the paper trading portfolio across all symbols",
            registry=self.registry,
        )
        self.cash_balance = Gauge(
            "cash_balance",
            "Current cash balance held by the paper trading portfolio",
            registry=self.registry,
        )
        self.position_qty = Gauge(
            "position_qty",
            "Current position quantity held by the paper trading portfolio per symbol",
            labelnames=["symbol"],
            registry=self.registry,
        )
        self.equity = Gauge(
            "equity",
            "Current total equity of the paper trading portfolio (cash + position value)",
            registry=self.registry,
        )
        self.equity_per_symbol = Gauge(
            "equity_per_symbol",
            "Market value of the held position per symbol (qty * last_price)",
            labelnames=["symbol"],
            registry=self.registry,
        )
        self.db_up = Gauge(
            "db_up",
            "1 when the Postgres connection pool is alive, 0 otherwise",
            registry=self.registry,
        )
        self.db_write_errors_total = Counter(
            "db_write_errors_total",
            "Total number of database write failures across all Postgres repositories",
            registry=self.registry,
        )
        self.rehydration_duration_seconds = Histogram(
            "rehydration_duration_seconds",
            "Time spent loading persisted portfolio state at startup",
            registry=self.registry,
        )
        self.replay_ticks_total = Counter(
            "replay_ticks_total",
            "Total number of ticks republished to NATS by the replay CLI",
            labelnames=["symbol"],
            registry=self.registry,
        )
        self.replay_duration_seconds = Histogram(
            "replay_duration_seconds",
            "Time spent running a single replay CLI invocation, from file open to completion",
            registry=self.registry,
        )

    def get_counter_value(self, counter: Counter, **labels: str) -> float | None:
        """Return the current value of a counter for the given label combination.

        Args:
            counter: The Counter instance to read from.
            **labels: Label name/value pairs (e.g. symbol="XBTUSD", side="BUY").

        Returns:
            The current float value of the counter for the specified labels,
            or None if no observations have been recorded yet.
        """
        for metric in counter.collect():
            for sample in metric.samples:
                sample_labels = getattr(sample, "labels", None)
                if sample_labels is not None and sample_labels == labels:
                    return sample.value
        return None
