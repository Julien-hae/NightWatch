"""MarketTickRecorder class for recording MarketTick data."""

import os

from Nightwatch.models.market_tick import MarketTick


class MarketTickRecorder:
    """Recorder for MarketTick data to a file in JSONL format."""

    def __init__(self, path: str) -> None:
        """Initialize the MarketTickRecorder with the file path."""
        self.filename = os.path.basename(path)
        self.folder = os.path.dirname(path)
        self.path = path
        if self.folder:
            os.makedirs(self.folder, exist_ok=True)

    def record_tick(self, tick: MarketTick) -> None:
        """Record a MarketTick to the file in JSONL format."""
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(tick.model_dump_json() + "\n")
