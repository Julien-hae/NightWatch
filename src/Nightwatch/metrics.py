"""Implements the NightwatchMetrics dataclass to define Prometheus metrics for the NightWatch service."""

from dataclasses import dataclass, field

from prometheus_client import CollectorRegistry, Counter


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
    ticks_published_total: Counter = field(init=False)
    ticks_consumed_total: Counter = field(init=False)
    signals_total: Counter = field(init=False)

    def __post_init__(self) -> None:
        """Create Prometheus counters bound to the instance registry."""
        self.ticks_received_total = Counter(
            "ticks_received_total",
            "Total number of ticks received from the exchange",
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
        self.signals_total = Counter(
            "signals_total",
            "Total number of trading signals emitted by the strategy",
            labelnames=["symbol", "side"],
            registry=self.registry,
        )

    def get_counter_value(self, counter: Counter, **labels: str) -> float:
        """Return the current value of a counter for the given label combination.

        Args:
            counter: The Counter instance to read from.
            **labels: Label name/value pairs (e.g. symbol="XBTUSD", side="BUY").

        Returns:
            The current float value of the counter for the specified labels,
            or 0.0 if no observations have been recorded yet.

        Example:
            >>> metrics.get_counter_value(metrics.signals_total, symbol="XBTUSD", side="BUY")
            3.0
        """
        return counter.labels(**labels)._value.get()  # type: ignore[no-any-return]
