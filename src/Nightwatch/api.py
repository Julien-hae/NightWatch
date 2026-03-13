"""FastAPI application exposing health and Prometheus metrics endpoints."""

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from Nightwatch.metrics import NightwatchMetrics
from Nightwatch.models.service_health import ServiceHealth


def create_app(
    health: ServiceHealth | None = None,
    metrics: NightwatchMetrics | None = None,
) -> FastAPI:
    """Create and return the FastAPI application.

    Args:
        health: Optional pre-configured health state (useful for testing).
        metrics: Optional pre-configured metrics (useful for testing).

    Returns:
        A fully configured FastAPI instance.
    """
    _health = health or ServiceHealth()
    _metrics = metrics or NightwatchMetrics()

    app = FastAPI(title="NightWatch API")

    @app.get("/healthz")
    def healthz() -> Response:
        """Return the health status of external connections."""
        if not _health.ws_connected or not _health.nats_connected:
            return JSONResponse(
                content={
                    "ws_connected": _health.ws_connected,
                    "nats_connected": _health.nats_connected,
                },
                status_code=503,
            )
        return JSONResponse(content={"ws_connected": _health.ws_connected, "nats_connected": _health.nats_connected}, status_code=200)

    @app.get("/metrics")
    def prometheus_metrics() -> Response:
        """Return Prometheus-format metrics."""
        return Response(content=generate_latest(_metrics.registry), media_type=CONTENT_TYPE_LATEST)

    return app
