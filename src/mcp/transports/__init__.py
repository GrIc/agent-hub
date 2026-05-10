"""MCP transport modules for the Agent Hub server.

This package provides transport-layer implementations for the MCP (Model
Context Protocol) server, supporting both Server-Sent Events (SSE) over HTTP
and standard I/O (stdio) for CLI-based clients.

Modules
-------
sse : FastAPI/ASGI-based SSE transport mounted under ``/mcp/sse``.
stdio : CLI entry point that runs the MCP server via stdio transport.

Usage
-----
SSE (programmatic)::

    from src.mcp.transports.sse import create_sse_app
    app = create_sse_app()

stdio (CLI)::

    python -m src.mcp.server --stdio

"""
