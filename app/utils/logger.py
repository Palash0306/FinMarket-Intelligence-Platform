# path: app/utils/logger.py

# =========================================================
# STRUCTURED LOGGER
# =========================================================
#
# What is a logger?
#
# A logger is like print() but professional.
#
# print("something happened") → appears in terminal, lost forever
# logger.info("something happened") → structured JSON, stored,
#                                      searchable, sent to CloudWatch
#
# Python's logging module has 5 levels:
#
# DEBUG    → detailed dev info (only visible in DEBUG=True)
# INFO     → normal operations (request received, task completed)
# WARNING  → something unexpected but recoverable (404, bad input)
# ERROR    → something failed (DB timeout, unhandled exception)
# CRITICAL → system is broken (cannot connect to DB at startup)

import logging
import json
import sys
from datetime import datetime, timezone
from app.config import settings


class JSONFormatter(logging.Formatter):
    """
    Custom log formatter that outputs JSON instead of plain text.

    Standard log format:
    2024-01-15 09:23:11 - ERROR - Something went wrong

    Our JSON format:
    {"timestamp": "2024-01-15T09:23:11Z", "level": "ERROR",
     "event": "Something went wrong", "service": "finmarket"}

    Why JSON?
    - CloudWatch can index and query individual fields
    - Grafana can build dashboards from log fields
    - You can grep for specific request_ids or error types
    """

    def format(self, record: logging.LogRecord) -> str:
        """
        Converts a log record to a JSON string.

        record.getMessage() returns the log message.
        record.__dict__ contains all extra fields passed
        via logger.info("msg", extra={"key": "value"})
        """

        # ── Base log structure ────────────────────────────
        log_entry = {
            # ISO 8601 timestamp with timezone — universal standard
            "timestamp": datetime.now(timezone.utc).isoformat(),

            # Log level: INFO, WARNING, ERROR etc.
            "level": record.levelname,

            # The log message itself
            "event": record.getMessage(),

            # Which file/module this log came from
            # Example: "app.api.stocks"
            "logger": record.name,

            # Service name for filtering in CloudWatch
            "service": "finmarket",

            # Current environment (development/production)
            "env": settings.app_env,
        }

        # ── Add extra fields ──────────────────────────────
        #
        # When you call logger.info("msg", extra={"key": "val"})
        # those extra fields get merged into the log entry.
        #
        # Standard logging.LogRecord fields to skip —
        # they're internal Python logging metadata we don't need
        skip_fields = {
            "name", "msg", "args", "levelname", "levelno",
            "pathname", "filename", "module", "exc_info",
            "exc_text", "stack_info", "lineno", "funcName",
            "created", "msecs", "relativeCreated", "thread",
            "threadName", "processName", "process", "message",
            "taskName"
        }

        for key, value in record.__dict__.items():
            if key not in skip_fields:
                log_entry[key] = value

        # ── Add exception info if present ─────────────────
        #
        # If this log was triggered by an exception,
        # include the traceback for debugging.
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


def get_logger(name: str) -> logging.Logger:
    """
    Creates and returns a configured logger.

    Usage:
        from app.utils.logger import get_logger
        logger = get_logger(__name__)
        logger.info("stock fetched", extra={"symbol": "AAPL"})

    Args:
        name: usually __name__ — gives the module path as logger name
              Example: "app.api.stocks"
    """

    logger = logging.getLogger(name)

    # ── Avoid duplicate handlers ──────────────────────────
    #
    # Python's logging is hierarchical — if you create the same
    # logger twice, you'd get duplicate log entries.
    # This check prevents that.
    if logger.handlers:
        return logger

    # ── Set log level ─────────────────────────────────────
    #
    # In DEBUG mode: show everything including DEBUG messages
    # In production: only INFO and above
    logger.setLevel(
        logging.DEBUG if settings.debug else logging.INFO
    )

    # ── Console handler ───────────────────────────────────
    #
    # StreamHandler sends logs to stdout (terminal/Docker logs)
    # This is what you see when you run docker compose up
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(JSONFormatter())
    logger.addHandler(console_handler)

    # ── Prevent propagation to root logger ───────────────
    #
    # Without this, logs would appear twice —
    # once from our handler, once from Python's root logger
    logger.propagate = False

    return logger