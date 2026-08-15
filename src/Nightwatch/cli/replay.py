"""CLI entrypoint to replay recorded MarketTick JSONL files.

Usage::

    poetry run replay --file data/ticks/2026-08-15/BTCUSD.jsonl --speed fast

Today this reads a tick file and reports how many ticks were parsed. Publishing
the ticks (fast/real speed control) is not implemented here yet.
"""

import argparse
import json
import logging

from Nightwatch.adapters.tick_replay_reader import TickReplayReader
from Nightwatch.common.logging_configuration import configure_logger

LOGGER = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse command-line arguments for the replay CLI."""
    parser = argparse.ArgumentParser(prog="replay", description="Replay recorded MarketTick JSONL files.")
    parser.add_argument("--file", required=True, help="Path to a JSONL file of recorded MarketTick objects.")
    parser.add_argument(
        "--speed",
        choices=["fast", "real"],
        default="fast",
        help="Replay speed. Reserved for the publish step; has no effect yet.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Read a MarketTick JSONL file and log a summary of the replay."""
    configure_logger()
    args = _parse_args(argv)

    reader = TickReplayReader(path=args.file)
    ticks = reader.read_ticks()

    LOGGER.info(
        json.dumps(
            {
                "event": "replay_end",
                "file": args.file,
                "speed": args.speed,
                "tick_count": len(ticks),
            },
        ),
    )


if __name__ == "__main__":
    main()
