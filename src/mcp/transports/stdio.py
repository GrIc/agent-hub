"""stdio transport for the Agent Hub MCP server.

This module provides a CLI entry point that runs the MCP server using the
stdio (standard I/O) transport. It is designed to be invoked via:

    python -m src.mcp.server --stdio

or directly:

    python -m src.mcp.transports.stdio

The stdio transport communicates with an MCP client by reading JSON-RPC
messages from the process's standard input and writing responses to standard
output. This is the primary transport for editor integrations (e.g., VS Code,
Neovim) and CLI tools.

Configuration
-------------
The following environment variables control transport behaviour:

``MCP_STDIO_LOG_LEVEL``
    Logging level for the stdio transport. Defaults to ``INFO``.

"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any, Optional

from src.config import load_config
from src.mcp.server import create_mcp_server

logger = logging.getLogger("mcp.transports.stdio")

# ---------------------------------------------------------------------------
# Module-level cache for the server instance to support idempotent calls.
# ---------------------------------------------------------------------------
_server_cache: Optional[Any] = None


def create_server() -> Any:
    """Create and return the MCP server instance.

    Server creation is delegated to :func:`src.mcp.server.create_mcp_server`.

    This function:

    1. Loads configuration via :func:`src.config.load_config`.
    2. Delegates server creation to :func:`src.mcp.server.create_mcp_server`.
    3. Caches the server instance so subsequent calls return the same object
       (idempotency).

    Returns
    -------
    mcp.server.Server
        A configured MCP Server instance.

    Raises
    ------
    ImportError
        If the MCP SDK is not installed.

    Examples
    --------
    >>> server = create_server()  # doctest: +SKIP
    >>> type(server).__name__  # doctest: +SKIP
    'Server'

    """
    global _server_cache

    if _server_cache is not None:
        logger.debug("Returning cached server instance")
        return _server_cache

    logger.info("Creating MCP server instance via src.mcp.server.create_mcp_server")

    cfg = load_config()
    server = create_mcp_server(cfg)

    _server_cache = server
    logger.info("MCP server created")
    return _server_cache


def run_stdio_server() -> None:
    """Run the MCP server using stdio transport.

    This function creates the server instance and starts the stdio transport
    loop. It reads messages from stdin and writes responses to stdout,
    following the JSON-RPC protocol defined by the MCP specification.

    The function runs indefinitely until interrupted (SIGINT/SIGTERM).

    Raises
    ------
    KeyboardInterrupt
        When the server is interrupted by the user.

    Examples
    --------
    Run the server::

        python -m src.mcp.transports.stdio

    """
    # Configure logging.
    log_level = os.getenv(
        "MCP_STDIO_LOG_LEVEL",
        load_config().get("mcp", {}).get("log_level", "INFO"),
    )
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        stream=sys.stderr,  # Log to stderr, messages go to stdout/stdin.
    )

    server = create_server()

    logger.info("Starting stdio transport server")
    logger.info(
        "Server is ready to receive messages on stdin and will respond on stdout"
    )

    try:
        server.run(transport="stdio")
    except KeyboardInterrupt:
        logger.info("Server shut down by user interrupt")


def build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser.

    Returns
    -------
    argparse.ArgumentParser
        A parser that accepts the ``--stdio`` flag to run the stdio server.

    """
    parser = argparse.ArgumentParser(
        prog="src.mcp.transports.stdio",
        description="Agent Hub MCP server with stdio transport",
    )
    parser.add_argument(
        "--stdio",
        action="store_true",
        default=True,  # Default to stdio for backward compatibility.
        help="Run the MCP server using stdio transport (default: True)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=None,
        help="Override the log level",
    )
    return parser


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()

    if args.log_level:
        logging.basicConfig(
            level=getattr(logging, args.log_level),
            format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
            stream=sys.stderr,
        )

    if args.stdio:
        run_stdio_server()
    else:
        parser.print_help()
        sys.exit(1)
