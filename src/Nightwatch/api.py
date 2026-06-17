"""FastAPI application exposing health and Prometheus metrics endpoints."""

import logging
import os

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from Nightwatch.database import DatabaseConnector
from Nightwatch.messaging.nats_connection import NatsConnector
from Nightwatch.metrics import NightwatchMetrics
from Nightwatch.models.service_health import ServiceHealth

LOGGER = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    """Read a boolean flag from environment variables."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def create_app(
    health: ServiceHealth | None = None,
    metrics: NightwatchMetrics | None = None,
    database: DatabaseConnector | None = None,
    nats: NatsConnector | None = None,
    health_require_ws: bool | None = None,
) -> FastAPI:
    """Create and return the FastAPI application.

    Args:
        health: Optional pre-configured health state (useful for testing).
        metrics: Optional pre-configured metrics (useful for testing).
        database: Optional database connector. When provided, ``/healthz`` performs
            a live ``SELECT 1`` ping on every call to report ``db_connected``.
        nats: Optional NATS connector used to track ``nats_connected`` status.
        health_require_ws: Whether ``ws_connected`` must be true for overall ``ok``.
            Defaults to ``HEALTH_REQUIRE_WS`` env var (default: true).

    Returns:
        A fully configured FastAPI instance.
    """
    _health = health or ServiceHealth()
    _metrics = metrics or NightwatchMetrics()
    _database = database
    if _database is None and os.environ.get("DATABASE_URL"):
        _database = DatabaseConnector()

    _nats = nats
    if _nats is None and os.environ.get("NATS_SERVERS"):
        _nats = NatsConnector(metrics=_metrics)

    require_ws = health_require_ws if health_require_ws is not None else _env_bool("HEALTH_REQUIRE_WS", default=True)

    if health is None:
        if _nats is None:
            _health.nats_connected = True
        if _database is None:
            _health.db_connected = True

    app = FastAPI(title="NightWatch API")

    @app.on_event("startup")
    async def startup() -> None:
        """Initialize optional dependency connections for health reporting."""
        if _nats is not None:
            try:
                await _nats.connect()
                _health.nats_connected = _nats.client.is_connected
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("NATS startup connect failed: %s", exc)
                _health.nats_connected = False

        if _database is not None and _database.configured:
            _health.db_connected = await _database.ping()

    @app.on_event("shutdown")
    async def shutdown() -> None:
        """Gracefully close long-lived connections."""
        if _nats is not None and _nats.client.is_connected:
            try:
                await _nats.close()
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("NATS shutdown close failed: %s", exc)

    @app.get("/healthz")
    async def healthz() -> Response:
        """Return the health status of external connections."""
        if _database is not None:
            _health.db_connected = await _database.ping()

        if _nats is not None:
            _health.nats_connected = _nats.client.is_connected

        checks = [_health.nats_connected, _health.db_connected]
        if require_ws:
            checks.insert(0, _health.ws_connected)

        ok = all(checks)
        body = {
            "ok": ok,
            "ws_connected": _health.ws_connected,
            "nats_connected": _health.nats_connected,
            "db_connected": _health.db_connected,
        }
        return JSONResponse(content=body, status_code=200 if ok else 503)

    @app.get("/metrics")
    def prometheus_metrics() -> Response:
        """Return Prometheus-format metrics."""
        return Response(content=generate_latest(_metrics.registry), media_type=CONTENT_TYPE_LATEST)

    return app
