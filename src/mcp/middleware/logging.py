"""Structured JSON logging middleware for the MCP server.

This module provides a ``JSONFormatter`` class that outputs log records as
JSON strings, along with a ``configure_logging()`` helper to set up the
MCP logger from a server entry point.

Example usage::

    from src.mcp.middleware.logging import configure_logging

    configure_logging()  # Sets up the ``mcp`` logger with JSON output.

"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class JSONFormatter(logging.Formatter):
    """A logging formatter that emits structured JSON log records.

    Each log record is serialized to a JSON string containing at minimum:

    - ``timestamp`` – ISO 8601 formatted time in UTC.
    - ``level`` – The logging level name (e.g. ``INFO``, ``ERROR``).
    - ``logger`` – The logger name.
    - ``message`` – The log message.

    Any extra attributes attached to the log record (via the ``extra``
    parameter in ``logger.info(..., extra={...})``) are also included in
    the output JSON.

    Example output::

        {"timestamp": "2024-01-15T14:30:25.123456+00:00", "level": "INFO",
         "logger": "mcp", "message": "Tool called", "tool": "read_file",
         "call_id": "abc-123"}

    """

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as a JSON string.

        Args:
            record: The log record to format.

        Returns:
            A JSON-encoded string containing the structured log data.

        """
        # Build the base dictionary with required fields.
        log_data: Dict[str, Any] = {
            "timestamp": self._format_timestamp(record.created),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Merge any extra attributes from the log record.
        for key, value in record.__dict__.items():
            # Skip standard logging attributes that are not useful in output.
            if key in (
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "getMessage",
                "taskName",
            ):
                continue
            log_data[key] = self._serialize(value)

        # Handle exceptions.
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            log_data["stack_info"] = self.formatStack(record.stack_info)

        return json.dumps(log_data, default=str)

    @staticmethod
    def _format_timestamp(timestamp: float) -> str:
        """Convert a Unix timestamp to an ISO 8601 string in UTC.

        Args:
            timestamp: Unix timestamp as returned by ``time.time()``.

        Returns:
            ISO 8601 formatted timestamp string with UTC timezone.

        """
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        return dt.isoformat()

    @staticmethod
    def _serialize(value: Any) -> Any:
        """Serialize a value for JSON output.

        Handles common types that might not be JSON-serializable by
        default, such as enums or custom objects.

        Args:
            value: The value to serialize.

        Returns:
            A JSON-serializable representation of the value.

        """
        import enum as enum_module
        
        if isinstance(value, enum_module.Enum):
                return value.value
        try:
            json.dumps(value)
            return value
        except (TypeError, ValueError):
            return str(value)


# Sentinel to track whether the logger has been configured.
_CONFIGURED: bool = False


def configure_logging(
    level: int = logging.INFO,
    logger_name: str = "mcp",
    stream: Optional[Any] = None,
) -> logging.Logger:
    """Configure and return the MCP logger with JSON formatting.

    This function sets up a logger with the specified name, attaches a
    ``StreamHandler`` that uses ``JSONFormatter``, and ensures that
    duplicate handlers are not added on repeated calls.

    Args:
        level: The logging level to set (default: ``logging.INFO``).
        logger_name: The name of the logger to configure (default: ``"mcp"``).
        stream: The stream to write log output to. Defaults to
            ``sys.stderr``.

    Returns:
        The configured logger instance.

    Example::

        logger = configure_logging(level=logging.DEBUG)
        logger.info("Server started", extra={"port": 8080})

    """
    global _CONFIGURED

    # Avoid adding duplicate handlers on repeated calls.
    if _CONFIGURED:
        return logging.getLogger(logger_name)

    logger = logging.getLogger(logger_name)
    logger.setLevel(level)

    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JSONFormatter())
    logger.addHandler(handler)

    _CONFIGURED = True

    return logger
