"""
web/workspace_routes.py — API routes for the workspace web interface.

Plugged into the main FastAPI app via `register_workspace_routes(app, cfg)`.
"""

import logging
import uuid
from pathlib import Path
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse, FileResponse

from src.workspace_session import SessionManager, ALL_WORKSPACE_AGENTS
from src.projects import list_projects, get_or_create_project
from src.agents.pipeline import PIPELINE_STEPS

logger = logging.getLogger(__name__)


def register_workspace_routes(app, cfg: dict, client, store):
    """Register all /workspace routes on the FastAPI app."""

    session_mgr = SessionManager(cfg, client, store, max_sessions=5)

    # -- Pages --

    @app.get("/workspace")
    async def workspace_page():
        return FileResponse("web/workspace.html")

    # -- Session management --

    @app.post("/api/ws/session")
    async def create_or_get_session(request: Request):
        body = await request.json()
        session_id = body.get("session_id") or str(uuid.uuid4())[:12]
        session = session_mgr.get_or_create(session_id)
        return session.get_state()

    # -- Projects --

    @app.get("/api/ws/projects")
    async def ws_list_projects():
        return {"projects": list_projects()}

    @app.post("/api/ws/projects")
    async def ws_create_project(request: Request):
        body = await request.json()
        name = body.get("name", "").strip()
        if not name:
            return JSONResponse({"error": "Project name required"}, status_code=400)
        project = get_or_create_project(name)
        return {"project": name, "status": "created"}

    @app.post("/api/ws/set-project")
    async def ws_set_project(request: Request):
        body = await request.json()
        session_id = body.get("session_id", "")
        project_name = body.get("project", "").strip()
        if not session_id or not project_name:
            return JSONResponse({"error": "session_id and project required"}, status_code=400)
        session = session_mgr.get_or_create(session_id)
        return session.set_project(project_name)

    # -- File browser --

    @app.get("/api/ws/projects/{name}/files")
    async def ws_project_files(name: str):
        project = get_or_create_project(name)
        tree = _build_file_tree(project)
        return {"project": name, "tree": tree}

    @app.get("/api/ws/projects/{name}/file")
    async def ws_read_file(name: str, path: str):
        project = get_or_create_project(name)
        full_path = project.root / path
        # Security: ensure path doesn't escape project root
        try:
            full_path = full_path.resolve()
            if not str(full_path).startswith(str(project.root.resolve())):
                return JSONResponse({"error": "Path traversal denied"}, status_code=403)
        except Exception:
            return JSONResponse({"error": "Invalid path"}, status_code=400)

        if not full_path.exists():
            return JSONResponse({"error": f"File not found: {path}"}, status_code=404)

        try:
            content = full_path.read_text(encoding="utf-8", errors="replace")
            return {
                "path": path,
                "content": content,
                "size": len(content),
                "name": full_path.name,
            }
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # -- Agent management --

    @app.get("/api/ws/agents")
    async def ws_list_agents():
        return ALL_WORKSPACE_AGENTS

    @app.post("/api/ws/switch-agent")
    async def ws_switch_agent(request: Request):
        body = await request.json()
        session_id = body.get("session_id", "")
        agent_name = body.get("agent", "")
        if not session_id or not agent_name:
            return JSONResponse({"error": "session_id and agent required"}, status_code=400)
        session = session_mgr.get_or_create(session_id)
        return session.switch_agent(agent_name)

    # -- Chat (messages + /commands) --

    @app.post("/api/ws/chat")
    async def ws_chat(request: Request):
        body = await request.json()
        session_id = body.get("session_id", "")
        message = body.get("message", "").strip()
        if not session_id:
            return JSONResponse({"error": "session_id required"}, status_code=400)
        if not message:
            return JSONResponse({"error": "Empty message"}, status_code=400)

        session = session_mgr.get(session_id)
        if not session:
            return JSONResponse({"error": "Session not found"}, status_code=404)

        import time
        start = time.time()
        result = session.chat(message)
        result["duration_ms"] = int((time.time() - start) * 1000)
        result["state"] = session.get_state()

        if "error" in result:
            return JSONResponse(result, status_code=400)
        return result

    # -- Pipeline --

    @app.get("/api/ws/pipeline/steps")
    async def ws_pipeline_steps():
        return {"steps": PIPELINE_STEPS}

    @app.post("/api/ws/pipeline/start")
    async def ws_pipeline_start(request: Request):
        body = await request.json()
        session_id = body.get("session_id", "")
        start_from = body.get("start_from", "")
        if not session_id:
            return JSONResponse({"error": "session_id required"}, status_code=400)
        session = session_mgr.get(session_id)
        if not session:
            return JSONResponse({"error": "Session not found"}, status_code=404)
        return session.start_pipeline(start_from)

    @app.post("/api/ws/pipeline/next")
    async def ws_pipeline_next(request: Request):
        body = await request.json()
        session_id = body.get("session_id", "")
        session = session_mgr.get(session_id)
        if not session:
            return JSONResponse({"error": "Session not found"}, status_code=404)
        return session.pipeline_next()

    @app.post("/api/ws/pipeline/skip")
    async def ws_pipeline_skip(request: Request):
        body = await request.json()
        session_id = body.get("session_id", "")
        session = session_mgr.get(session_id)
        if not session:
            return JSONResponse({"error": "Session not found"}, status_code=404)
        return session.pipeline_skip()

    @app.post("/api/ws/pipeline/abort")
    async def ws_pipeline_abort(request: Request):
        body = await request.json()
        session_id = body.get("session_id", "")
        session = session_mgr.get(session_id)
        if not session:
            return JSONResponse({"error": "Session not found"}, status_code=404)
        return session.pipeline_abort()

    # -- Session state --

    @app.get("/api/ws/session/{session_id}")
    async def ws_session_state(session_id: str):
        session = session_mgr.get(session_id)
        if not session:
            return JSONResponse({"error": "Session not found"}, status_code=404)
        return session.get_state()

    @app.get("/api/ws/stats")
    async def ws_stats():
        return {
            "active_sessions": session_mgr.count,
            "max_sessions": session_mgr.max_sessions,
        }


def _build_file_tree(project) -> list[dict]:
    """
    Build a file tree for the project.
    Returns a list of {name, type, path, children} dicts.
    """
    tree = []
    for subdir_name in ["notes", "outputs", "reports"]:
        subdir = project.root / subdir_name
        if not subdir.exists():
            continue
        node = {
            "name": subdir_name,
            "type": "dir",
            "path": subdir_name,
            "children": _scan_dir(subdir, subdir_name),
        }
        tree.append(node)
    return tree


def _scan_dir(directory: Path, relative_base: str) -> list[dict]:
    """Recursively scan a directory into a tree structure."""
    items = []
    try:
        entries = sorted(directory.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
    except PermissionError:
        return items

    for entry in entries:
        if entry.name.startswith("."):
            continue
        rel_path = f"{relative_base}/{entry.name}"
        if entry.is_dir():
            items.append({
                "name": entry.name,
                "type": "dir",
                "path": rel_path,
                "children": _scan_dir(entry, rel_path),
            })
        else:
            items.append({
                "name": entry.name,
                "type": "file",
                "path": rel_path,
                "size": entry.stat().st_size,
            })
    return items