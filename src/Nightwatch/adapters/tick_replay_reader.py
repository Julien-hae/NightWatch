"""TickReplayReader class for reading MarketTick data recorded in JSONL files."""

import logging
from collections.abc import Iterator

from pydantic import ValidationError

from Nightwatch.metrics.metrics import NightwatchMetrics
from Nightwatch.models.market_tick import MarketTick

LOGGER = logging.getLogger(__name__)


class TickReplayReader:
    """Reader for MarketTick data recorded to a file in JSONL format."""

    def __init__(self, path: str, metrics: NightwatchMetrics | None = None) -> None:
        """Initialize the TickReplayReader with the file path."""
        self.path = path
        self._metrics = metrics

    def iter_ticks(self) -> Iterator[MarketTick]:
        """Yield MarketTick objects read from the file, in their original order.

        Lines that are blank are skipped silently. Lines that are not valid JSON
        or do not satisfy the MarketTick schema are logged and skipped, without
        raising, so a single corrupt line never aborts a replay.
        """
        with open(self.path, "r", encoding="utf-8") as f:
            for line_number, raw_line in enumerate(f, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    yield MarketTick.model_validate_json(line)
                except ValidationError as exc:
                    if self._metrics is not None:
                        self._metrics.parse_errors_total.inc()
                    LOGGER.error(
                        "Error parsing tick at %s:%d. exc=%s",
                        self.path,
                        line_number,
                        exc,
                    )

    def read_ticks(self) -> list[MarketTick]:
        """Read all MarketTick objects from the file, in their original order."""
        return list(self.iter_ticks())
