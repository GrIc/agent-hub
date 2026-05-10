"""SSE transport for the Agent Hub MCP server.

This module creates a FastAPI application that exposes the MCP server as an
SSE (Server-Sent Events) endpoint under ``/mcp/sse``. Clients establish an
SSE connection to receive server messages and POST their requests to the
configured message endpoint.

The transport is designed to be imported and used programmatically:

    from src.mcp.transports.sse import create_sse_app

    app = create_sse_app()
    # Mount or run ``app`` with any ASGI server (uvicorn, hypercorn, etc.)

It can also be run directly as a script for quick development:

    python -m src.mcp.transports.sse

Configuration
-------------
The following environment variables control transport behaviour:

``MCP_SSE_HOST``
    Bind address for the server. Defaults to ``127.0.0.1``.

``MCP_SSE_PORT``
    Port to listen on. Defaults to ``8000``.

``MCP_SSE_ENDPOINT``
    Relative path where the client POSTs messages. Defaults to ``/messages/``.

``MCP_SSE_SSE_PATH``
    Relative path where the SSE endpoint is mounted. Defaults to ``/mcp/sse``.

"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from src.config import load_config

logger = logging.getLogger("mcp.transports.sse")

# ---------------------------------------------------------------------------
# Module-level cache to ensure idempotent calls return the same app instance.
# ---------------------------------------------------------------------------
_app_cache: Optional[Any] = None


def _get_sse_config() -> dict[str, Any]:
    """Load and return SSE-specific configuration.

    Reads ``config.yaml`` (via :func:`src.config.load_config`) and extracts
    the ``mcp.sse`` section. Falls back to sensible defaults when the
    section is absent.

    Returns
    -------
    dict[str, Any]
        A dictionary with keys ``host``, ``port``, ``endpoint``, and
        ``sse_path``.

    """
    cfg = load_config()
    mcp_cfg = cfg.get("mcp", {})
    sse_cfg = mcp_cfg.get("sse", {})

    host = sse_cfg.get("host", os.getenv("MCP_SSE_HOST", "127.0.0.1"))
    port = sse_cfg.get("port", int(os.getenv("MCP_SSE_PORT", "8000")))
    endpoint = sse_cfg.get("endpoint", os.getenv("MCP_SSE_ENDPOINT", "/messages/"))
    sse_path = sse_cfg.get("path", os.getenv("MCP_SSE_SSE_PATH", "/mcp/sse"))

    return {
        "host": host,
        "port": port,
        "endpoint": endpoint,
        "sse_path": sse_path,
    }


def create_sse_app(app: Any = None) -> Any:
    """Create and return a FastAPI application configured for SSE transport.

    This function:

    1. Imports FastAPI lazily to avoid hard dependencies when only the
       stdio transport is needed.
    2. If no ``app`` is provided, instantiates a new ``FastAPI`` application.
    3. Calls :func:`src.mcp.server.mount_mcp_sse` to attach the SSE and
       message routes using the shared MCP server implementation.
    4. Caches the app instance so subsequent calls return the same object
       (idempotency).

    Parameters
    ----------
    app : fastapi.FastAPI or None
        An optional existing FastAPI application to mount the MCP routes on.
        If ``None``, a new ``FastAPI`` app is instantiated.

    Returns
    -------
    fastapi.FastAPI
        A configured FastAPI application ready to be served by any ASGI
        server.

    Raises
    ------
    ImportError
        If FastAPI or its dependencies are not installed.

    Examples
    --------
    >>> app = create_sse_app()  # doctest: +SKIP
    >>> type(app).__name__
    'FastAPI'

    >>> from fastapi import FastAPI
    >>> existing = FastAPI()
    >>> result = create_sse_app(existing)  # doctest: +SKIP
    >>> result is existing
    True

    """
    global _app_cache

    if _app_cache is not None:
        logger.debug("Returning cached SSE app instance")
        return _app_cache

    # Lazy imports to keep this module lightweight when only stdio is used.
    try:
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware
    except ImportError as exc:
        raise ImportError(
            "SSE transport requires FastAPI. "
            "Install it with: pip install fastapi"
        ) from exc

    logger.info("Creating SSE transport application")

    # Instantiate a new FastAPI app if none was provided.
    if app is None:
        app = FastAPI()
        created_new = True
    else:
        created_new = False

    # Import the mount function from the shared MCP server.
    from src.mcp.server import mount_mcp_sse

    cfg = load_config()
    mount_mcp_sse(app, cfg)

    # Add CORS middleware if configured (mount_mcp_sse does not handle CORS).
    mcp_cfg = cfg.get("mcp", {})
    cors_cfg = mcp_cfg.get("cors", {})
    if cors_cfg.get("enabled", False):
        origins = cors_cfg.get("allow_origins", ["*"])
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=cors_cfg.get("allow_credentials", True),
            allow_methods=cors_cfg.get("allow_methods", ["GET", "POST"]),
            allow_headers=cors_cfg.get("allow_headers", ["*"]),
        )
        logger.info("CORS middleware enabled with origins: %s", origins)

    _app_cache = app
    logger.info(
        "SSE app created: %s routes mounted on %s",
        "new" if created_new else "existing",
        id(app),
    )
    return _app_cache


def run_sse_server() -> None:
    """Run the SSE server directly as a script.

    This function is useful for development and testing. It creates the SSE
    app and starts an uvicorn server with the configured host and port.

    Raises
    ------
    ImportError
        If uvicorn is not installed.

    Examples
    --------
    Run the server::

        python -m src.mcp.transports.sse

    """
    import uvicorn

    sse_cfg = _get_sse_config()

    logger.info(
        "Starting SSE server on %s:%d (path=%s, endpoint=%s)",
        sse_cfg["host"],
        sse_cfg["port"],
        sse_cfg["sse_path"],
        sse_cfg["endpoint"],
    )

    app = create_sse_app()

    uvicorn.run(
        app,
        host=sse_cfg["host"],
        port=sse_cfg["port"],
        log_level=os.getenv("UVICORN_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
    )
    run_sse_server()
