"""Production entrypoint that wires the full NightWatch pipeline.

Orchestrates:

* persistence bootstrap (migrations + asyncpg pool + repos),
* portfolio rehydration from the database,
* Kraken WebSocket ingestion → StrategyRunner → PaperTrader → atomic DB write,
* JetStream control-event subscriber (kill switch backlog drain + live updates),
* FastAPI (``/healthz`` and ``/metrics``) on the same event loop,
* graceful shutdown on SIGINT/SIGTERM.

Run as ``python -m Nightwatch.main`` (used by the container ``CMD``).
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from collections.abc import Awaitable
from dataclasses import dataclass
from decimal import Decimal

import uvicorn

from Nightwatch.adapters.kraken_adapter import KrakenAdapter
from Nightwatch.api import create_app
from Nightwatch.common.logging_configuration import configure_logger
from Nightwatch.db.bootstrap import bootstrap_persistence
from Nightwatch.db.database import DatabaseConnector
from Nightwatch.db.repositories import PaperTraderRepos
from Nightwatch.messaging.control_event_subscriber import ControlEventSubscriber
from Nightwatch.messaging.nats_connection import NatsConnector
from Nightwatch.metrics.metrics import NightwatchMetrics
from Nightwatch.models.bot_control_event import BotControlEvent
from Nightwatch.models.nats_config import NatsConnectionConfig
from Nightwatch.models.order_factory import OrderFactoryConfig
from Nightwatch.models.paper_execution import PercentageFeeModel
from Nightwatch.models.portfolio import Portfolio
from Nightwatch.models.service_health import ServiceHealth
from Nightwatch.models.tick_buffer import TickBuffer
from Nightwatch.pipeline.kill_switch import KillSwitch
from Nightwatch.pipeline.paper_trader import PaperTrader
from Nightwatch.pipeline.risk_engine import RiskEngine
from Nightwatch.pipeline.strategy_runner import StrategyRunner
from Nightwatch.strategies.momentum_burst import MomentumBurstStrategy

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunConfig:
    """Runtime configuration sourced from environment variables."""

    symbol: str
    initial_cash: Decimal
    order_notional: Decimal
    fee_rate: Decimal
    window_sec: float
    threshold_pct: float
    database_url: str
    nats_servers: str | None
    http_host: str
    http_port: int

    @classmethod
    def from_env(cls) -> "RunConfig":
        """Build a config from ``os.environ``; raise when ``DATABASE_URL`` is unset."""
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL must be set for production startup")
        return cls(
            symbol=os.environ.get("TRADE_SYMBOL", "BTC/USD"),
            initial_cash=Decimal(os.environ.get("INITIAL_CASH", "10000")),
            order_notional=Decimal(os.environ.get("ORDER_NOTIONAL", "100")),
            fee_rate=Decimal(os.environ.get("FEE_RATE", "0.001")),
            window_sec=float(os.environ.get("STRATEGY_WINDOW_SEC", "10.0")),
            threshold_pct=float(os.environ.get("STRATEGY_THRESHOLD_PCT", "0.30")),
            database_url=database_url,
            nats_servers=os.environ.get("NATS_SERVERS"),
            http_host=os.environ.get("HTTP_HOST", "0.0.0.0"),  # noqa: S104
            http_port=int(os.environ.get("HTTP_PORT", "8000")),
        )


async def _safe_close(label: str, coro: Awaitable[object]) -> None:
    """Await *coro* and log any exception without re-raising."""
    try:
        await coro
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("%s close failed: %s", label, exc)


async def _connect_nats(
    cfg: RunConfig,
    kill_switch: KillSwitch,
    metrics: NightwatchMetrics,
) -> tuple[NatsConnector, ControlEventSubscriber] | None:
    """Connect NATS + control subscriber, drain backlog. Return ``None`` if disabled."""
    if not cfg.nats_servers:
        kill_switch.mark_ready()
        return None
    nats_config = NatsConnectionConfig(servers=cfg.nats_servers.split(","))
    nats_connector = NatsConnector(config=nats_config, metrics=metrics)
    await nats_connector.connect()

    control_sub = ControlEventSubscriber(config=nats_config, metrics=metrics)
    await control_sub.connect()

    async def _on_control(event: BotControlEvent) -> None:
        kill_switch.apply(event)

    drained = await control_sub.drain_backlog(kill_switch)
    LOGGER.info("Drained %d backlog control event(s)", drained)
    await control_sub.subscribe(cb=_on_control)
    return nats_connector, control_sub


def _install_signal_handlers(stop_event: asyncio.Event, server: uvicorn.Server) -> None:
    """Wire SIGINT/SIGTERM to flip *stop_event* and request server exit."""

    def _request_stop(signame: str) -> None:
        LOGGER.info("Received %s, initiating graceful shutdown", signame)
        stop_event.set()
        server.should_exit = True

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop, sig.name)
        except NotImplementedError:
            pass  # Windows / restricted environments — best effort only.


async def _run() -> None:
    """Build and run the full pipeline until cancelled."""
    configure_logger()
    cfg = RunConfig.from_env()

    metrics = NightwatchMetrics()
    health = ServiceHealth()
    kill_switch = KillSwitch(metrics=metrics, ready=False)

    persistence = await bootstrap_persistence(cfg.database_url, metrics=metrics)

    portfolio = Portfolio(cash=cfg.initial_cash, positions={}, last_prices={})
    paper_trader = PaperTrader(
        portfolio=portfolio,
        order_factory_config=OrderFactoryConfig(order_notional=cfg.order_notional),
        fee_model=PercentageFeeModel(rate=cfg.fee_rate),
        metrics=metrics,
        repos=PaperTraderRepos.from_context(persistence),
    )
    await paper_trader.rehydrate()

    runner = StrategyRunner(
        strategy=MomentumBurstStrategy(window_sec=cfg.window_sec, threshold_pct=cfg.threshold_pct, metric=metrics),
        buffer=TickBuffer(),
        metric=metrics,
        risk_engine=RiskEngine.create_default(metrics=metrics),
        kill_switch=kill_switch,
        paper_trader=paper_trader,
    )

    nats_pair = await _connect_nats(cfg, kill_switch, metrics)
    nats_connector = nats_pair[0] if nats_pair else None
    control_sub = nats_pair[1] if nats_pair else None
    health.nats_connected = nats_connector.client.is_connected if nats_connector else True

    database = DatabaseConnector(database_url=cfg.database_url, pool=persistence.pool)
    health.db_connected = await database.ping()

    app = create_app(
        health=health,
        metrics=metrics,
        database=database,
        nats=nats_connector,
        health_require_ws=False,
    )
    kraken = KrakenAdapter(symbol=cfg.symbol, metrics=metrics)

    async def _ingest_ticks() -> None:
        async for tick in kraken.stream_ticks():
            health.ws_connected = True
            try:
                await runner.on_market_tick_async(tick)
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Tick processing failed for %s: %s", tick.symbol, exc)

    server = uvicorn.Server(
        uvicorn.Config(app, host=cfg.http_host, port=cfg.http_port, log_config=None, lifespan="on"),
    )
    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event, server)

    ingest_task = asyncio.create_task(_ingest_ticks(), name="kraken-ingest")
    server_task = asyncio.create_task(server.serve(), name="uvicorn-server")
    stop_task = asyncio.create_task(stop_event.wait(), name="stop-event")

    try:
        done, _ = await asyncio.wait({ingest_task, server_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            exc = task.exception()
            if exc is not None and not isinstance(exc, asyncio.CancelledError):
                LOGGER.error("Task %s exited with: %s", task.get_name(), exc)
    finally:
        server.should_exit = True
        for task in (ingest_task, stop_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(ingest_task, server_task, stop_task, return_exceptions=True)

        if control_sub is not None:
            await _safe_close("Control subscriber", control_sub.close())
        if nats_connector is not None and nats_connector.client.is_connected:
            await _safe_close("NATS", nats_connector.close())
        await _safe_close("Kraken", kraken.close())
        await persistence.close()
        LOGGER.info("Shutdown complete")


def main() -> None:
    """Synchronous entrypoint used by the container CMD."""
    asyncio.run(_run())


if __name__ == "__main__":
    main()
