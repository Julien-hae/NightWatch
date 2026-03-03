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

    def __post_init__(self) -> None:
        """Create Prometheus counters bound to the instance registry."""
        self.ticks_received_total = Counter(
            "ticks_received_total",
            "Total number of ticks received from the exchange",
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
