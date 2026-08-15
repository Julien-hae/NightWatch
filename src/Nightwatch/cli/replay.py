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
import time

from Nightwatch.adapters.tick_replay_reader import TickReplayReader
from Nightwatch.common.logging_configuration import configure_logger
from Nightwatch.messaging.publisher import MarketTickPublisher
from Nightwatch.metrics.metrics import NightwatchMetrics
from Nightwatch.models.market_tick import MarketTick

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
    return parser.parse_args(argv)


async def _sleep_for_real_speed(previous: MarketTick | None, tick: MarketTick) -> None:
    """Sleep to reproduce the original gap between *previous* and *tick*, if any."""
    if previous is None:
        return
    delay = (tick.timestamp - previous.timestamp).total_seconds()
    if delay > 0:
        await asyncio.sleep(delay)


async def _run(args: argparse.Namespace, metrics: NightwatchMetrics) -> None:
    """Read a MarketTick JSONL file and republish every tick to NATS."""
    LOGGER.info(
        json.dumps({"event": "replay_start", "file": args.file, "speed": args.speed}),
    )
    start_time = time.monotonic()

    reader = TickReplayReader(path=args.file, metrics=metrics)
    publisher = MarketTickPublisher(metrics=metrics)
    await publisher.connect()

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
            previous = tick
        await publisher.client.flush(timeout=5)
    finally:
        await publisher.close()

    duration_seconds = time.monotonic() - start_time
    metrics.replay_duration_seconds.observe(duration_seconds)

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
