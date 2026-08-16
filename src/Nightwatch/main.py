"""Production entrypoint that wires the full NightWatch pipeline.

Orchestrates:

* persistence bootstrap (migrations + asyncpg pool + repos),
* portfolio rehydration from the database,
* Kraken WebSocket ingestion → StrategyRunner → PaperTrader → atomic DB write,
* best-effort tick broadcast over NATS core (``MarketTickPublisher``) for any
  interested external subscribers,
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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

import uvicorn

from Nightwatch.adapters.kraken_adapter import KrakenAdapter
from Nightwatch.api import create_app
from Nightwatch.common.logging_configuration import configure_logger
from Nightwatch.db.bootstrap import PersistenceContext, bootstrap_persistence
from Nightwatch.db.database import DatabaseConnector
from Nightwatch.db.repositories import AsyncKillSwitchStateRepo, PaperTraderRepos
from Nightwatch.messaging.control_event_subscriber import ControlEventSubscriber
from Nightwatch.messaging.nats_connection import NatsConnector
from Nightwatch.messaging.publisher import MarketTickPublisher
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

_INGEST_SHUTDOWN_GRACE_SEC = 5.0


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
    require_kill_switch: bool

    @classmethod
    def from_env(cls) -> "RunConfig":
        """Build a config from ``os.environ``.

        Raises:
            RuntimeError: ``DATABASE_URL`` is unset, or ``REQUIRE_KILL_SWITCH`` is
                truthy while ``NATS_SERVERS`` is unset — checked here, before any
                other startup work (migrations, DB pool, rehydration), so a
                deployment that must not run without a working kill switch fails
                immediately instead of silently starting ungated.
        """
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL must be set for production startup")
        nats_servers = os.environ.get("NATS_SERVERS")
        require_kill_switch = os.environ.get("REQUIRE_KILL_SWITCH", "false").strip().lower() in {"1", "true", "yes", "on"}
        if require_kill_switch and not nats_servers:
            raise RuntimeError(
                "REQUIRE_KILL_SWITCH is set but NATS_SERVERS is unset: refusing to start without a working "
                "kill switch. Set NATS_SERVERS, or unset REQUIRE_KILL_SWITCH to accept running ungated."
            )
        return cls(
            symbol=os.environ.get("TRADE_SYMBOL", "BTC/USD"),
            initial_cash=Decimal(os.environ.get("INITIAL_CASH", "10000")),
            order_notional=Decimal(os.environ.get("ORDER_NOTIONAL", "100")),
            fee_rate=Decimal(os.environ.get("FEE_RATE", "0.001")),
            window_sec=float(os.environ.get("STRATEGY_WINDOW_SEC", "10.0")),
            threshold_pct=float(os.environ.get("STRATEGY_THRESHOLD_PCT", "0.30")),
            database_url=database_url,
            nats_servers=nats_servers,
            http_host=os.environ.get("HTTP_HOST", "0.0.0.0"),  # noqa: S104
            http_port=int(os.environ.get("HTTP_PORT", "8000")),
            require_kill_switch=require_kill_switch,
        )


async def _safe_close(label: str, coro: Awaitable[object]) -> None:
    """Await *coro* and log any exception without re-raising."""
    try:
        await coro
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("%s close failed: %s", label, exc)


def _nats_reconnect_callbacks(
    label: str, metrics: NightwatchMetrics
) -> tuple[Callable[[], Awaitable[None]], Callable[[], Awaitable[None]]]:
    """Build disconnect/reconnect callbacks that log and record metrics for a named NATS connection.

    This is what makes reconnection after a NATS restart observable in Loki/Grafana — nats.py
    reconnects and resumes publish/subscribe on its own, but without these callbacks nothing
    would surface that an outage happened.
    """

    async def _on_disconnected() -> None:
        LOGGER.warning("NATS connection '%s' disconnected; nats.py will attempt to reconnect.", label)
        metrics.nats_disconnects_total.labels(connection=label).inc()

    async def _on_reconnected() -> None:
        LOGGER.info("NATS connection '%s' reconnected.", label)
        metrics.nats_reconnects_total.labels(connection=label).inc()

    return _on_disconnected, _on_reconnected


async def _restore_kill_switch_from_postgres(
    kill_switch: KillSwitch,
    kill_switch_state_repo: AsyncKillSwitchStateRepo,
) -> None:
    """Fall back to the last Postgres-recorded kill-switch state.

    Called only when the JetStream backlog drain found nothing to apply —
    either a fresh control stream, or (more dangerously) a kill command whose
    stream retention (10k messages / 24h) has since lapsed. An empty backlog
    is not evidence that trading was never killed, so this checks Postgres
    before letting ``KillSwitch`` fall back to its own ``trading_enabled=True``
    default.
    """
    persisted = await kill_switch_state_repo.get()
    if persisted is None:
        LOGGER.info("No persisted kill-switch state in Postgres either; defaulting to trading_enabled=True.")
        return
    LOGGER.warning(
        "JetStream control backlog was empty (fresh stream, or the last control event fell outside its "
        "retention window); restoring kill-switch state from Postgres instead: trading_enabled=%s reason=%s",
        persisted.trading_enabled,
        persisted.reason,
    )
    kill_switch.apply(BotControlEvent(kill=not persisted.trading_enabled, reason=persisted.reason, timestamp=persisted.updated_at))


async def _connect_nats(
    cfg: RunConfig,
    kill_switch: KillSwitch,
    metrics: NightwatchMetrics,
    kill_switch_state_repo: AsyncKillSwitchStateRepo | None = None,
) -> tuple[NatsConnector, ControlEventSubscriber, MarketTickPublisher] | None:
    """Connect NATS + control subscriber + tick publisher, drain backlog. Return ``None`` if disabled."""
    if not cfg.nats_servers:
        LOGGER.critical(
            "NATS_SERVERS is unset: running without a kill switch. BotControlEvents will never be "
            "received, so trading cannot be halted remotely — only by stopping this process. Set "
            "REQUIRE_KILL_SWITCH=true to refuse to start in this state instead."
        )
        metrics.kill_switch_available.set(0)
        kill_switch.mark_ready()
        return None
    metrics.kill_switch_available.set(1)
    nats_config = NatsConnectionConfig(servers=cfg.nats_servers.split(","))

    nats_connector = NatsConnector(config=nats_config, metrics=metrics)
    on_disconnected, on_reconnected = _nats_reconnect_callbacks("nats_connector", metrics)
    await nats_connector.connect(on_disconnected=on_disconnected, on_reconnected=on_reconnected)

    control_sub = ControlEventSubscriber(config=nats_config, metrics=metrics)
    on_disconnected, on_reconnected = _nats_reconnect_callbacks("control_subscriber", metrics)
    await control_sub.connect(on_disconnected=on_disconnected, on_reconnected=on_reconnected)

    async def _on_control(event: BotControlEvent) -> None:
        kill_switch.apply(event)
        if kill_switch_state_repo is not None:
            await kill_switch_state_repo.save(trading_enabled=not event.kill, reason=event.reason, updated_at=event.timestamp)

    drained = await control_sub.drain_backlog(kill_switch)
    LOGGER.info("Drained %d backlog control event(s)", drained)
    if kill_switch_state_repo is not None:
        if drained:
            # Mirror the restored state into Postgres so a *future* restart, after this
            # event has aged out of JetStream's retention window, still recovers it.
            await kill_switch_state_repo.save(
                trading_enabled=kill_switch.trading_enabled,
                reason="restored from JetStream backlog",
                updated_at=datetime.now(timezone.utc),
            )
        else:
            await _restore_kill_switch_from_postgres(kill_switch, kill_switch_state_repo)
    await control_sub.subscribe(cb=_on_control)

    tick_publisher = MarketTickPublisher(config=nats_config, metrics=metrics)
    on_disconnected, on_reconnected = _nats_reconnect_callbacks("tick_publisher", metrics)
    await tick_publisher.connect(on_disconnected=on_disconnected, on_reconnected=on_reconnected)

    return nats_connector, control_sub, tick_publisher


async def _ingest_ticks(
    kraken: KrakenAdapter,
    runner: StrategyRunner,
    health: ServiceHealth,
    tick_publisher: MarketTickPublisher | None,
    stop_event: asyncio.Event,
) -> None:
    """Stream ticks from Kraken, best-effort publish them, then run them through the pipeline.

    Checks *stop_event* only after a tick has fully finished the pipeline (publish -> strategy ->
    risk -> paper-trade -> atomic DB write), never mid-processing, so a shutdown signal can never
    interrupt an in-flight trade write. See ``_run``'s shutdown sequence for the bounded wait that
    gives this loop a chance to reach that checkpoint before falling back to a hard cancel.
    """
    async for tick in kraken.stream_ticks():
        health.ws_connected = True
        if tick_publisher is not None:
            try:
                # flush=False: don't pay a round-trip per tick on the hot ingest path; the NATS
                # client flushes its write buffer on its own cadence, and a publish failure here
                # must never block the trading pipeline below.
                await tick_publisher.publish(tick, flush=False)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Failed to publish tick %s to NATS: %s", tick.uid, exc)
        try:
            await runner.on_market_tick_async(tick)
        except Exception as exc:  # noqa: BLE001
            # No retry: a transient Postgres failure here (already reverted in-memory by
            # process_and_persist, so memory still matches the DB) permanently drops this
            # one signal rather than risk reprocessing it — the tick that produced it is
            # gone once this loop moves on, so "retry" would mean replaying an old signal
            # against current portfolio state, not the original tick. Deliberate fail-closed
            # design for a paper-trading bot; watch db_write_errors_total / db_up (with
            # alerting — see prometheus.yml) to notice when this is happening.
            LOGGER.exception("Tick processing failed for %s: %s", tick.symbol, exc)
        if stop_event.is_set():
            LOGGER.info("Stop requested; finished in-flight tick, exiting ingest loop.")
            break


async def _shutdown_resources(
    *,
    control_sub: ControlEventSubscriber | None,
    tick_publisher: MarketTickPublisher | None,
    nats_connector: NatsConnector | None,
    kraken: KrakenAdapter,
    persistence: PersistenceContext,
) -> None:
    """Drain NATS connections, close the Kraken WebSocket, then close the DB pool.

    ``NatsConnector.close()`` calls ``drain()`` (not a bare disconnect), which stops accepting new
    work and flushes in-flight publishes/subscriptions before the connection closes;
    ``persistence.close()`` closes the asyncpg pool, which waits for connections to finish their
    current query. Order matters: NATS first so no new control/tick traffic arrives while the DB
    is going away, then the DB.
    """
    LOGGER.info("Draining NATS connections...")
    if control_sub is not None:
        await _safe_close("Control subscriber", control_sub.close())
    if tick_publisher is not None:
        await _safe_close("Tick publisher", tick_publisher.close())
    if nats_connector is not None and nats_connector.client.is_connected:
        await _safe_close("NATS", nats_connector.close())
    await _safe_close("Kraken", kraken.close())
    LOGGER.info("Closing database connections...")
    await persistence.close()
    LOGGER.info("Shutdown complete")


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

    nats_bundle = await _connect_nats(cfg, kill_switch, metrics, persistence.kill_switch_state_repo)
    nats_connector = nats_bundle[0] if nats_bundle else None
    control_sub = nats_bundle[1] if nats_bundle else None
    tick_publisher = nats_bundle[2] if nats_bundle else None
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

    server = uvicorn.Server(
        uvicorn.Config(app, host=cfg.http_host, port=cfg.http_port, log_config=None, lifespan="on"),
    )
    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event, server)

    ingest_task = asyncio.create_task(_ingest_ticks(kraken, runner, health, tick_publisher, stop_event), name="kraken-ingest")
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
        stop_event.set()
        if not stop_task.done():
            stop_task.cancel()
        if not ingest_task.done():
            # Bounded wait for the in-flight tick (if any) to finish its DB write before we give
            # up and cancel — see _ingest_ticks' stop_event checkpoint.
            _, pending = await asyncio.wait({ingest_task}, timeout=_INGEST_SHUTDOWN_GRACE_SEC)
            if pending:
                LOGGER.warning("Ingest task did not stop within %.0fs; cancelling.", _INGEST_SHUTDOWN_GRACE_SEC)
                ingest_task.cancel()
        await asyncio.gather(ingest_task, server_task, stop_task, return_exceptions=True)

        await _shutdown_resources(
            control_sub=control_sub,
            tick_publisher=tick_publisher,
            nats_connector=nats_connector,
            kraken=kraken,
            persistence=persistence,
        )


def main() -> None:
    """Synchronous entrypoint used by the container CMD."""
    asyncio.run(_run())


if __name__ == "__main__":
    main()
