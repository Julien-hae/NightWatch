"""CLI entrypoint to replay recorded MarketTick JSONL files.

Usage::

    poetry run replay --file data/ticks/2026-08-15/BTCUSD.jsonl --speed fast

Reads a tick file and republishes every tick to NATS on ``market.tick.<SYMBOL>``,
the same subject the live Kraken ingest pipeline uses. ``--speed fast`` publishes
immediately; ``--speed real`` sleeps between ticks based on the deltas between
their recorded timestamps, reproducing the original cadence.
"""

import argparse
import asyncio
import json
import logging
import os
import time
from decimal import Decimal

from Nightwatch.adapters.tick_replay_reader import TickReplayReader
from Nightwatch.common.logging_configuration import configure_logger
from Nightwatch.messaging.publisher import MarketTickPublisher
from Nightwatch.metrics.metrics import NightwatchMetrics
from Nightwatch.models.market_tick import MarketTick
from Nightwatch.models.order_factory import OrderFactoryConfig
from Nightwatch.models.paper_execution import PercentageFeeModel
from Nightwatch.models.portfolio import Portfolio
from Nightwatch.models.tick_buffer import TickBuffer
from Nightwatch.pipeline.capture import PipelineCapture
from Nightwatch.pipeline.paper_trader import PaperTrader
from Nightwatch.pipeline.risk_engine import RiskEngine
from Nightwatch.pipeline.strategy_runner import StrategyRunner
from Nightwatch.strategies.momentum_burst import MomentumBurstStrategy

LOGGER = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse command-line arguments for the replay CLI."""
    parser = argparse.ArgumentParser(prog="replay", description="Replay recorded MarketTick JSONL files.")
    parser.add_argument("--file", required=True, help="Path to a JSONL file of recorded MarketTick objects.")
    parser.add_argument(
        "--speed",
        choices=["fast", "real"],
        default="fast",
        help="Replay speed: 'fast' publishes immediately, 'real' sleeps between ticks based on their timestamps.",
    )
    parser.add_argument(
        "--capture-file",
        default=None,
        help=(
            "Optional path to write a deterministic JSON capture of the signals, orders and fills "
            "produced by replaying the ticks through an in-memory strategy pipeline. UUIDs are "
            "normalized and timestamps derived from the replayed ticks, so replaying the same file "
            "twice produces identical output — for regression ('golden') testing."
        ),
    )
    return parser.parse_args(argv)


async def _sleep_for_real_speed(previous: MarketTick | None, tick: MarketTick) -> None:
    """Sleep to reproduce the original gap between *previous* and *tick*, if any."""
    if previous is None:
        return
    delay = (tick.timestamp - previous.timestamp).total_seconds()
    if delay > 0:
        await asyncio.sleep(delay)


def _build_capture_pipeline(metrics: NightwatchMetrics) -> tuple[StrategyRunner, PipelineCapture]:
    """Build an in-memory strategy pipeline wired to a fresh :class:`PipelineCapture` sink.

    Sizing and strategy configuration mirror ``main.py``'s production env vars, so a
    replay-driven capture run uses the same parameters as a live deployment configured
    the same way. The pipeline runs fully in-memory: no database or NATS involvement.
    """
    capture = PipelineCapture()
    portfolio = Portfolio(cash=Decimal(os.environ.get("INITIAL_CASH", "10000")), positions={}, last_prices={})
    paper_trader = PaperTrader(
        portfolio=portfolio,
        order_factory_config=OrderFactoryConfig(order_notional=Decimal(os.environ.get("ORDER_NOTIONAL", "100"))),
        fee_model=PercentageFeeModel(rate=Decimal(os.environ.get("FEE_RATE", "0.001"))),
        metrics=metrics,
        capture=capture,
    )
    runner = StrategyRunner(
        strategy=MomentumBurstStrategy(
            window_sec=float(os.environ.get("STRATEGY_WINDOW_SEC", "10.0")),
            threshold_pct=float(os.environ.get("STRATEGY_THRESHOLD_PCT", "0.30")),
            metric=metrics,
        ),
        buffer=TickBuffer(),
        metric=metrics,
        risk_engine=RiskEngine.create_default(metrics=metrics),
        paper_trader=paper_trader,
        capture=capture,
    )
    return runner, capture


async def _run(args: argparse.Namespace, metrics: NightwatchMetrics) -> None:
    """Read a MarketTick JSONL file and republish every tick to NATS."""
    LOGGER.info(
        json.dumps({"event": "replay_start", "file": args.file, "speed": args.speed}),
    )
    start_time = time.monotonic()

    reader = TickReplayReader(path=args.file, metrics=metrics)
    publisher = MarketTickPublisher(metrics=metrics)
    await publisher.connect()

    capture_pipeline = _build_capture_pipeline(metrics) if args.capture_file else None

    published = 0
    failed = 0
    previous: MarketTick | None = None
    try:
        for tick in reader.iter_ticks():
            if args.speed == "real":
                await _sleep_for_real_speed(previous, tick)
            try:
                await publisher.publish(tick, flush=False)
                published += 1
                metrics.replay_ticks_total.labels(symbol=tick.symbol).inc()
            except Exception as exc:  # noqa: BLE001
                failed += 1
                LOGGER.warning("Failed to publish tick %s to NATS: %s", tick.uid, exc)
            if capture_pipeline is not None:
                capture_pipeline[0].on_market_tick(tick)
            previous = tick
        await publisher.client.flush(timeout=5)
    finally:
        await publisher.close()

    duration_seconds = time.monotonic() - start_time
    metrics.replay_duration_seconds.observe(duration_seconds)

    if capture_pipeline is not None:
        capture = capture_pipeline[1]
        capture.write(args.capture_file)
        LOGGER.info(
            json.dumps({"event": "replay_capture_written", "file": args.capture_file, "events": len(capture.events())}),
        )

    LOGGER.info(
        json.dumps(
            {
                "event": "replay_end",
                "file": args.file,
                "speed": args.speed,
                "tick_count": published + failed,
                "published": published,
                "failed": failed,
                "duration_seconds": duration_seconds,
            },
        ),
    )


def main(argv: list[str] | None = None, metrics: NightwatchMetrics | None = None) -> None:
    """Parse args and run the replay CLI to completion."""
    configure_logger()
    args = _parse_args(argv)
    asyncio.run(_run(args, metrics if metrics is not None else NightwatchMetrics()))


if __name__ == "__main__":
    main()
