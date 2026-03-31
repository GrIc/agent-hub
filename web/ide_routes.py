"""
web/ide_routes.py — REST API routes for IDE integration.

These routes provide a simplified REST interface for VS Code and IntelliJ
extensions that don't use MCP directly. The MCP server (src/mcp_server.py)
is the preferred integration path, but these REST endpoints serve as a
fallback and for simpler client implementations.

Plugged into the main FastAPI app via `register_ide_routes(app, cfg)`.
"""

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from src.mcp_server import AgentHubBridge

logger = logging.getLogger(__name__)


def register_ide_routes(app, cfg: dict):
    """Register all /api/ide/* routes on the FastAPI app."""

    bridge = AgentHubBridge(cfg)

    @app.post("/api/ide/ask")
    async def ide_ask(request: Request):
        """Ask the expert agent a question."""
        body = await request.json()
        question = body.get("question", "").strip()
        if not question:
            return JSONResponse({"error": "question required"}, status_code=400)
        try:
            answer = bridge.expert_ask(question)
            return {"answer": answer}
        except Exception as e:
            logger.exception("IDE ask failed")
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.post("/api/ide/search")
    async def ide_search(request: Request):
        """Search the RAG index."""
        body = await request.json()
        query = body.get("query", "").strip()
        top_k = body.get("top_k", 8)
        if not query:
            return JSONResponse({"error": "query required"}, status_code=400)
        try:
            results = bridge.search_rag(query, top_k=top_k)
            return {"results": results}
        except Exception as e:
            logger.exception("IDE search failed")
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.post("/api/ide/read-file")
    async def ide_read_file(request: Request):
        """Read a workspace file."""
        body = await request.json()
        filepath = body.get("filepath", "").strip()
        if not filepath:
            return JSONResponse({"error": "filepath required"}, status_code=400)
        result = bridge.read_file(filepath)
        if "error" in result:
            return JSONResponse(result, status_code=404)
        return result

    @app.post("/api/ide/edit-file")
    async def ide_edit_file(request: Request):
        """Write content to a workspace file."""
        body = await request.json()
        filepath = body.get("filepath", "").strip()
        content = body.get("content", "")
        if not filepath:
            return JSONResponse({"error": "filepath required"}, status_code=400)
        result = bridge.edit_file(filepath, content)
        if "error" in result:
            return JSONResponse(result, status_code=500)
        return result

    @app.get("/api/ide/deliverables")
    async def ide_list_deliverables(project: str = ""):
        """List deliverables for a project."""
        if not project:
            return JSONResponse({"error": "project query param required"}, status_code=400)
        deliverables = bridge.list_deliverables(project)
        return {"deliverables": deliverables}

    @app.post("/api/ide/read-deliverable")
    async def ide_read_deliverable(request: Request):
        """Read a specific deliverable."""
        body = await request.json()
        project = body.get("project", "").strip()
        filename = body.get("filename", "").strip()
        if not project or not filename:
            return JSONResponse(
                {"error": "project and filename required"}, status_code=400
            )
        result = bridge.read_deliverable(project, filename)
        if "error" in result:
            return JSONResponse(result, status_code=404)
        return result

    @app.post("/api/ide/apply-deliverable")
    async def ide_apply_deliverable(request: Request):
        """Apply a deliverable (parse spec → generate file edits)."""
        body = await request.json()
        project = body.get("project", "").strip()
        filename = body.get("filename", "").strip()
        dry_run = body.get("dry_run", True)
        if not project or not filename:
            return JSONResponse(
                {"error": "project and filename required"}, status_code=400
            )
        try:
            result = bridge.apply_deliverable(project, filename, dry_run=dry_run)
            return result
        except Exception as e:
            logger.exception("Apply deliverable failed")
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.get("/api/ide/workspace-tree")
    async def ide_workspace_tree():
        """Get workspace directory tree."""
        tree = bridge.workspace_tree()
        return {"tree": tree}

    logger.info("IDE REST routes registered at /api/ide/*")
