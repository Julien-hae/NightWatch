"""Logging customization."""

import json
import logging
import logging.config
import os
import time
from typing import Any

LOGGER = logging.getLogger(__name__)


class UTCFormatter(logging.Formatter):
    """UTC formatter which converts timestamps to UTC."""

    converter = time.gmtime


class JSONFormatter(logging.Formatter):
    """Structured JSON formatter for log shipping to Loki."""

    converter = time.gmtime

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as a single-line JSON object."""
        log_entry = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, default=str)


LOGGING_CONFIG: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "utc": {
            "()": UTCFormatter,
            "format": "%(asctime)s - %(process)d - %(name)s - %(levelname)s - %(message)s",
            "datefmt": "%Y-%m-%dT%H:%M:%S%z",
        },
        "json": {
            "()": JSONFormatter,
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "utc"},
    },
    "root": {"handlers": ["console"]},
}


def configure_logger() -> None:
    """Configure logging.

    Configures a console logger which logs in UTC time with timestamps
    formatted according to ISO 8601.

    When LOG_FORMAT is set to "json", logs are emitted as structured JSON
    for ingestion by Loki/Promtail.

    Note: loglevel defaults to logging.INFO and may be overridden by
    configuring the environment variable 'LOG_LEVEL'.
    """
    log_format = os.environ.get("LOG_FORMAT", "text").lower()
    if log_format == "json":
        LOGGING_CONFIG["handlers"]["console"]["formatter"] = "json"

    logging.config.dictConfig(LOGGING_CONFIG)
    loglevel_name = os.environ.get("LOG_LEVEL", default="INFO")
    loglevel = logging.getLevelName(loglevel_name)
    if isinstance(loglevel, str):
        LOGGER.warning(
            "Loglevel-Name '%s' not found in loglevels. Falling back to INFO.",
            loglevel_name,
        )
        loglevel = logging.INFO

    # Set loglevel on root logger and propagate.
    logging.getLogger().setLevel(loglevel)
