"""MCP server entry point for Agent Hub.

This module replaces the legacy ``src/mcp_server.py`` and provides a clean,
modular entry point for the Model Context Protocol (MCP) server.  It:

- Loads configuration via :func:`src.config.load_config`.
- Auto‑discovers tools from the ``src.mcp.tools`` package using the
  registry (:func:`src.mcp.registry.discover_tools`).
- Mounts an SSE transport on an existing FastAPI application.
- Supports standalone execution via ``python -m src.mcp.server``.

Structured JSON logging is handled through the ``mcp.server`` logger namespace.

Usage
-----
Standalone (stdio transport)::

    python -m src.mcp.server

Integrated with FastAPI::

    from fastapi import FastAPI
    from src.mcp.server import create_mcp_server, mount_mcp_sse

    cfg = load_config()
    app = FastAPI()
    mount_mcp_sse(app, cfg)

"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Optional

from src.config import load_config

logger = logging.getLogger("mcp.server")

# ---------------------------------------------------------------------------
# Module-level cache to ensure idempotent calls return the same server instance.
# ---------------------------------------------------------------------------
_server_cache: Optional[Any] = None


def _check_mcp_sdk() -> bool:
    """Verify that the ``mcp`` SDK is installed.

    Returns
    -------
    bool
        ``True`` if the SDK is available, ``False`` otherwise.  Logs an
        error message when the SDK is missing.

    """
    try:
        import mcp  # noqa: F401
        return True
    except ImportError:
        logger.error(
            "MCP SDK not installed. Run: pip install mcp[server] --break-system-packages"
        )
        return False


def create_mcp_server(cfg: dict) -> Any:
    """Create and configure the MCP server instance.

    This function:

    1. Validates that the ``mcp`` SDK is available.
    2. Auto‑discovers all concrete :class:`~src.mcp.base.BaseTool` subclasses
       from the ``src.mcp.tools`` package via
       :func:`src.mcp.registry.discover_tools`.
    3. Registers each discovered tool with the MCP ``Server`` instance,
       mapping tool names to their handler implementations.
    4. Exposes a ``workspace://tree`` resource that returns the workspace
       directory tree.

    Parameters
    ----------
    cfg : dict
        Configuration dictionary produced by :func:`src.config.load_config`.

    Returns
    -------
    mcp.server.Server or None
        The configured MCP ``Server`` instance, or ``None`` if the SDK is
        not available.

    Raises
    ------
    KeyError
        If required configuration keys are missing.

    Examples
    --------
    >>> cfg = load_config()  # doctest: +SKIP
    >>> server = create_mcp_server(cfg)  # doctest: +SKIP
    >>> type(server).__name__  # doctest: +SKIP
    'Server'

    """
    global _server_cache

    if _server_cache is not None:
        logger.debug("Returning cached MCP server instance")
        return _server_cache

    if not _check_mcp_sdk():
        return None

    # Lazy imports to keep this module lightweight when only the registry
    # or other transports are needed.
    try:
        from mcp.server import Server
        from mcp.types import TextContent, Tool, Resource
        from pydantic import AnyUrl
    except ImportError as exc:
        raise ImportError(
            "MCP server requires the mcp SDK. "
            "Install it with: pip install mcp[server]"
        ) from exc

    # ------------------------------------------------------------------
    # Build the Agent Hub bridge (tool implementations).
    # ------------------------------------------------------------------
    bridge = _AgentHubBridge(cfg)

    # ------------------------------------------------------------------
    # Auto‑discover tools from the registry.
    # ------------------------------------------------------------------
    tool_registry = discover_tools()
    logger.info(
        "Discovered %d tool(s) from registry.", len(tool_registry)
    )

    # ------------------------------------------------------------------
    # Create the MCP Server instance.
    # ------------------------------------------------------------------
    server = Server("agent-hub")

    # -- Tool definitions ------------------------------------------------

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """List all available MCP tools."""
        tools: list[Tool] = []

        for tool_name, tool_instance in tool_registry.items():
            tools.append(
                Tool(
                    name=tool_name,
                    description=getattr(tool_instance, "description", ""),
                    inputSchema=getattr(tool_instance, "input_schema", {}),
                )
            )

        # Always expose the workspace tree resource as a tool for convenience.
        tools.append(
            Tool(
                name="workspace_tree",
                description=(
                    "Return the workspace directory tree as text. "
                    "Useful for getting an overview of the codebase structure."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "max_depth": {
                            "type": "integer",
                            "description": "Maximum directory depth (default: 3)",
                            "default": 3,
                        },
                    },
                    "required": [],
                },
            )
        )

        return tools

    # -- Tool call handler -----------------------------------------------

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        """Route tool calls to the appropriate handler."""
        try:
            # Route through discovered tools first.
            if name in tool_registry:
                tool_instance = tool_registry[name]
                # BaseTool.__call__ expects args and optional context.
                result = tool_instance(arguments, context={})
                return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

            # Handle built‑in tools that are not in the registry.
            if name == "workspace_tree":
                max_depth = arguments.get("max_depth", 3)
                tree_text = await asyncio.to_thread(bridge.workspace_tree, max_depth=max_depth)
                return [TextContent(type="text", text=tree_text)]

            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        except Exception as e:
            logger.exception("Tool '%s' failed", name)
            return [TextContent(type="text", text=f"Error: {e}")]

    # -- Resources -------------------------------------------------------

    @server.list_resources()
    async def list_resources() -> list[Resource]:
        """List available MCP resources."""
        return [
            Resource(
                uri=AnyUrl("workspace://tree"),
                name="Workspace file tree",
                mimeType="text/plain",
                description="Directory tree of the indexed codebase",
            ),
        ]

    @server.read_resource()
    async def read_resource(uri: Any) -> str:
        """Read a resource by URI."""
        if str(uri) == "workspace://tree":
            return await asyncio.to_thread(bridge.workspace_tree)
        return f"Unknown resource: {uri}"

    _server_cache = server
    logger.info("MCP server created with %d tool(s).", len(tool_registry))
    return _server_cache


def mount_mcp_sse(app: Any, cfg: dict) -> None:
    """Mount the MCP server as an SSE endpoint on an existing FastAPI app.

    This function configures the MCP server and mounts two routes on the
    provided FastAPI application:

    - ``GET /mcp/sse`` — SSE connection endpoint for event streaming.
    - ``POST /mcp/messages`` — JSON‑RPC message endpoint for client requests.

    Parameters
    ----------
    app : fastapi.FastAPI
        The FastAPI application to mount the MCP SSE endpoint on.
    cfg : dict
        Configuration dictionary produced by :func:`src.config.load_config`.

    Raises
    ------
    ImportError
        If FastAPI or the MCP SDK are not installed.

    Examples
    --------
    >>> from fastapi import FastAPI  # doctest: +SKIP
    >>> from src.mcp.server import mount_mcp_sse, load_config  # doctest: +SKIP
    >>> app = FastAPI()  # doctest: +SKIP
    >>> mount_mcp_sse(app, load_config())  # doctest: +SKIP

    """
    if not _check_mcp_sdk():
        logger.warning("MCP SDK not available — IDE integration disabled")
        return

    try:
        from mcp.server.sse import SseServerTransport
        from starlette.routing import Route, Mount
    except ImportError as exc:
        raise ImportError(
            "SSE transport requires starlette. "
            "Install it with: pip install starlette"
        ) from exc

    server = create_mcp_server(cfg)
    if server is None:
        return

    sse_transport = SseServerTransport("/mcp/messages")

    async def handle_sse(request: Any) -> Any:
        """Handle SSE connection from IDE client."""
        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(
                streams[0],
                streams[1],
                server.create_initialization_options(),
            )

    async def handle_messages(request: Any) -> Any:
        """Handle JSON-RPC messages from IDE client."""
        return await sse_transport.handle_post_message(
            request.scope, request.receive, request._send
        )

    # Mount as sub-application under /mcp.
    app.mount(
        "/mcp",
        Mount(
            "/mcp",
            routes=[
                Route(
                    "/sse",
                    endpoint=handle_sse,
                    methods=["GET"],
                    media_type="text/event-stream",
                ),
                Route(
                    "/messages",
                    endpoint=handle_messages,
                    methods=["POST"],
                ),
            ],
        ),
    )
    logger.info("MCP SSE endpoint mounted at /mcp/sse")


def main() -> None:
    """Run the MCP server standalone with stdio transport.

    This function is useful for development and local IDE testing.  It
    loads configuration, creates the MCP server, and runs it over stdio
    so that any MCP‑compatible client can connect directly.

    Returns
    -------
    None

    Raises
    ------
    SystemExit
        If the MCP SDK is not installed.

    Examples
    --------
    Run the server::

        python -m src.mcp.server

    """
    if not _check_mcp_sdk():
        sys.exit(1)

    from mcp.server.stdio import stdio_server

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
    )

    cfg = load_config()
    server = create_mcp_server(cfg)
    if server is None:
        sys.exit(1)

    print("Agent Hub MCP server starting (stdio transport)...", file=sys.stderr)

    async def run() -> None:
        """Run the MCP server over stdio."""
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Agent Hub Bridge — tool implementations.
# ---------------------------------------------------------------------------

class _AgentHubBridge:
    """Thin bridge between MCP tool calls and Agent Hub internals.

    Reuses the same :class:`~src.client.ResilientClient`,
    :class:`~src.rag.store.VectorStore`, and agent instances that the
    web UI and CLI use.

    Parameters
    ----------
    cfg : dict
        Configuration dictionary produced by :func:`src.config.load_config`.

    """

    def __init__(self, cfg: dict) -> None:
        from src.client import ResilientClient
        from src.rag.store import VectorStore
        from src.config import (
            get_model_for_agent,
            get_agent_temperature,
            get_agent_extra_params,
            build_custom_dsl_context,
            build_domain_context,
        )

        # Store for use in lazy‑init methods
        self._get_model_for_agent = get_model_for_agent
        self._get_agent_temperature = get_agent_temperature
        self._get_agent_extra_params = get_agent_extra_params

        self.cfg = cfg
        defaults = cfg.get("_defaults", {})
        self.workspace = Path(defaults.get("workspace_path", "./workspace")).resolve()

        # Shared infrastructure
        self.client = ResilientClient(
            api_key=defaults["api_key"],
            base_url=defaults["api_base_url"],
            max_retries=defaults.get("retry_max_attempts", 8),
            base_delay=defaults.get("retry_base_delay", 2.0),
            max_delay=defaults.get("retry_max_delay", 120.0),
        )

        embed_model = cfg["models"].get("embed", "")
        rerank_model = cfg["models"].get("rerank", "")
        self.store = VectorStore(
            client=self.client,
            embed_model=embed_model,
            rerank_model=rerank_model,
        )

        graph_cfg = cfg.get("graph", {})
        if graph_cfg.get("enabled", False):
            from src.rag.graph import KnowledgeGraph
            persist_dir = graph_cfg.get("persist_dir", ".graphdb")
            self.store.graph = KnowledgeGraph(persist_dir=persist_dir)

        self.dsl_context = build_custom_dsl_context(cfg)
        self.domain_context = build_domain_context(cfg)

        # Lazily initialized agents
        self._expert: Any = None

    def _get_expert(self) -> Any:
        """Lazy‑init the expert agent.

        Returns
        -------
        BaseAgent
            The configured expert agent instance.

        """
        if self._expert is None:
            from src.agents.base import BaseAgent

            class ExpertMCP(BaseAgent):
                name = "expert"

            self._expert = ExpertMCP(
                client=self.client,
                store=self.store,
                model=self._get_model_for_agent(self.cfg, "expert"),
                temperature=self._get_agent_temperature(self.cfg, "expert"),
                rag_top_k=self.cfg.get("rag", {}).get("top_k", 8),
                custom_dsl_info=self.dsl_context,
                domain_info=self.domain_context,
                extra_params=self._get_agent_extra_params(self.cfg, "expert"),
            )
        return self._expert

    # -- Tool implementations -----------------------------------------------

    def expert_ask(self, question: str) -> str:
        """Ask the expert agent a question with full RAG context.

        Parameters
        ----------
        question : str
            The question to ask the expert agent.

        Returns
        -------
        str
            The expert agent's response.

        """
        expert = self._get_expert()
        response = expert.chat(question)
        return response

    def search_rag(self, query: str, top_k: int = 8) -> list[dict]:
        """Search the RAG index directly.

        Parameters
        ----------
        query : str
            Search query (keywords or natural language).
        top_k : int
            Number of results to return (default: 8).

        Returns
        -------
        list[dict]
            List of result dictionaries with ``text``, ``source``,
            ``score``, and ``doc_level`` keys.

        """
        results = self.store.search_hybrid(query, top_k=top_k)
        return [
            {
                "text": r["text"],
                "source": r["source"],
                "score": round(r.get("rerank_score", r.get("score", 0)), 4),
                "doc_level": r.get("doc_level", ""),
            }
            for r in results
        ]

    def search_graph(self, entity: str, max_hops: int = 2) -> dict:
        """Query the knowledge graph for entity relationships.

        Parameters
        ----------
        entity : str
            Entity name to search for.
        max_hops : int
            BFS traversal depth (default: 2).

        Returns
        -------
        dict
            Graph search results including matches, neighbors, and summary.

        """
        graph_cfg = self.cfg.get("graph", {})
        if not graph_cfg.get("enabled", False):
            return {
                "error": "Knowledge graph is not enabled. "
                "Set graph.enabled: true in config.yaml"
            }

        from src.rag.graph import KnowledgeGraph
        persist_dir = graph_cfg.get("persist_dir", ".graphdb")
        graph = KnowledgeGraph(persist_dir=persist_dir)

        if graph.node_count == 0:
            return {"error": "Knowledge graph is empty. Run: python build_graph.py"}

        # Find matching entities
        matches = graph.find_entities(entity, threshold=0.6)
        if not matches:
            return {
                "entity": entity,
                "matches": [],
                "message": "No matching entities found",
            }

        # BFS from top matches
        all_neighbors: dict[str, int] = {}
        for node_id, confidence in matches[:3]:
            neighbors = graph.get_neighbors(node_id, max_hops=max_hops)
            for nid, hop in neighbors.items():
                if nid not in all_neighbors or hop < all_neighbors[nid]:
                    all_neighbors[nid] = hop

        summary = graph.get_subgraph_summary(all_neighbors)
        return {
            "entity": entity,
            "matches": [{"id": m[0], "confidence": round(m[1], 3)} for m in matches[:5]],
            "neighbor_count": len(all_neighbors),
            "summary": summary,
            "stats": graph.stats(),
        }

    def read_file(self, filepath: str) -> dict:
        """Read a file from the workspace.

        Parameters
        ----------
        filepath : str
            Relative path from workspace root.

        Returns
        -------
        dict
            Dictionary with ``filepath``, ``content``, and ``size`` keys,
            or an ``error`` key if the operation fails.

        """
        full = self.workspace / filepath
        if not full.resolve().is_relative_to(self.workspace):
            return {"error": "Path traversal blocked", "filepath": filepath}
        if not full.exists():
            return {"error": "File not found", "filepath": filepath}
        try:
            content = full.read_text(encoding="utf-8", errors="replace")
            return {
                "filepath": filepath,
                "content": content,
                "size": full.stat().st_size,
            }
        except Exception as e:
            return {"error": str(e), "filepath": filepath}

    def edit_file(self, filepath: str, content: str, create_dirs: bool = True) -> dict:
        """Write content to a workspace file.

        Parameters
        ----------
        filepath : str
            Relative path from workspace root.
        content : str
            Full file content to write.
        create_dirs : bool
            Create parent directories if needed (default: True).

        Returns
        -------
        dict
            Result dictionary with ``filepath``, ``status``, and ``size``
            keys, or an ``error`` key if the operation fails.

        """
        full = self.workspace / filepath
        if not full.resolve().is_relative_to(self.workspace):
            return {"error": "Path traversal blocked", "filepath": filepath}
        try:
            if create_dirs:
                full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content, encoding="utf-8")
            return {
                "filepath": filepath,
                "status": "written",
                "size": len(content.encode("utf-8")),
            }
        except Exception as e:
            return {"error": str(e), "filepath": filepath}

    def list_deliverables(self, project: str) -> list[dict]:
        """List all pipeline deliverables for a project.

        Parameters
        ----------
        project : str
            Project name.

        Returns
        -------
        list[dict]
            List of deliverable dictionaries with ``filename``, ``type``,
            ``version``, ``size``, and ``path`` keys.

        """
        project_dir = Path("projects") / project / "outputs"
        if not project_dir.exists():
            return []

        import re

        deliverables: list[dict] = []
        for f in sorted(project_dir.glob("*.md"), reverse=True):
            match = re.match(r"^(.+?)_v(\d+)\.md$", f.name)
            if match:
                deliverables.append({
                    "filename": f.name,
                    "type": match.group(1),
                    "version": int(match.group(2)),
                    "size": f.stat().st_size,
                    "path": str(f),
                })
            else:
                deliverables.append({
                    "filename": f.name,
                    "type": f.stem,
                    "version": 0,
                    "size": f.stat().st_size,
                    "path": str(f),
                })
        return deliverables

    def read_deliverable(self, project: str, filename: str) -> dict:
        """Read a specific pipeline deliverable.

        Parameters
        ----------
        project : str
            Project name.
        filename : str
            Deliverable filename.

        Returns
        -------
        dict
            Dictionary with ``filename``, ``content``, and ``size`` keys,
            or an ``error`` key if the operation fails.

        """
        filepath = Path("projects") / project / "outputs" / filename
        if not filepath.exists():
            return {"error": f"Deliverable not found: {filename}"}
        try:
            content = filepath.read_text(encoding="utf-8")
            return {
                "filename": filename,
                "content": content,
                "size": filepath.stat().st_size,
            }
        except Exception as e:
            return {"error": str(e)}

    def apply_deliverable(
        self,
        project: str,
        filename: str,
        dry_run: bool = True,
    ) -> dict:
        """Parse a pipeline deliverable and generate file edits.

        This is the killer feature: it reads a deliverable (e.g., a
        specifier output), extracts actionable tasks using the expert
        agent, and generates proposed file edits.

        Parameters
        ----------
        project : str
            Project name.
        filename : str
            Deliverable filename to implement.
        dry_run : bool
            If ``True`` (default), only propose edits. If ``False``,
            apply them directly.

        Returns
        -------
        dict
            Result dictionary with ``deliverable``, ``project``,
            ``dry_run``, ``task_count``, and ``edits`` keys.

        """
        import re

        # 1. Read the deliverable
        deliverable = self.read_deliverable(project, filename)
        if "error" in deliverable:
            return deliverable

        content = deliverable["content"]

        # 2. Ask the expert to analyze the deliverable and extract a task list
        expert = self._get_expert()

        analysis_prompt = (
            "You are analyzing a pipeline deliverable to extract implementable tasks.\n\n"
            "DELIVERABLE CONTENT:\n"
            f"```markdown\n{content}\n```\n\n"
            "Extract a structured list of file modifications needed. "
            "For each modification, output a JSON object with:\n"
            "- `filepath`: relative path from workspace root\n"
            "- `action`: create | modify | delete\n"
            "- `description`: what to do\n"
            "- `details`: specific implementation details from the spec\n\n"
            "Output ONLY a JSON array, no other text. Example:\n"
            '```json\n[\n  {"filepath": "src/auth.py", "action": "modify", '
            '"description": "Add JWT refresh", "details": "..."}\n]\n```'
        )

        try:
            analysis_response = expert.chat(analysis_prompt)
        except Exception as e:
            return {"error": f"Analysis failed: {e}"}

        # Parse the JSON task list
        json_match = re.search(r"```json\s*([\s\S]*?)```", analysis_response)
        if not json_match:
            # Try raw JSON
            json_match = re.search(r"\[[\s\S]*\]", analysis_response)
            if json_match:
                raw_json = json_match.group(0)
            else:
                return {
                    "error": "Could not extract task list from analysis",
                    "raw_analysis": analysis_response,
                }
        else:
            raw_json = json_match.group(1)

        try:
            tasks = json.loads(raw_json)
        except json.JSONDecodeError as e:
            return {"error": f"Invalid JSON in task list: {e}", "raw": raw_json}

        # 3. For each task, generate the edit
        edits: list[dict] = []
        for task in tasks:
            filepath = task.get("filepath", "")
            action = task.get("action", "modify")
            description = task.get("description", "")
            details = task.get("details", "")

            # Read existing file if modifying
            existing_content = ""
            if action == "modify":
                file_data = self.read_file(filepath)
                existing_content = file_data.get("content", "")

            # Use expert RAG to get context about the file/module
            rag_context = self.search_rag(f"{filepath} {description}", top_k=4)
            rag_text = "\n---\n".join(r["text"][:500] for r in rag_context)

            # Ask the expert agent to generate the new file content
            edit_prompt = (
                f"Task: {description}\n"
                f"Details: {details}\n"
                f"File: {filepath}\n"
                f"Action: {action}\n\n"
            )

            if existing_content:
                # Cap existing content to avoid token overflow
                if len(existing_content) > 8000:
                    existing_content = existing_content[:8000] + "\n[... truncated]"
                edit_prompt += f"EXISTING FILE CONTENT:\n```\n{existing_content}\n```\n\n"

            if rag_text:
                edit_prompt += f"RAG CONTEXT (related code):\n{rag_text}\n\n"

            edit_prompt += (
                "Generate the COMPLETE new file content. "
                "Do NOT use diff format — output the full file wrapped in "
                "```{language} blocks. Be precise and preserve existing functionality."
            )

            try:
                edit_response = expert.chat(edit_prompt)
            except Exception as e:
                edits.append({
                    "filepath": filepath,
                    "action": action,
                    "status": "error",
                    "error": str(e),
                })
                continue

            # Extract code block from response
            code_match = re.search(r"```\w*\s*\n([\s\S]*?)```", edit_response)
            new_content = code_match.group(1) if code_match else edit_response

            edit_entry = {
                "filepath": filepath,
                "action": action,
                "description": description,
                "content": new_content,
                "status": "proposed",
            }

            if not dry_run and action != "delete":
                result = self.edit_file(filepath, new_content)
                if "error" in result:
                    edit_entry["status"] = "error"
                    edit_entry["error"] = result["error"]
                else:
                    edit_entry["status"] = "applied"

            if not dry_run and action == "delete":
                full = self.workspace / filepath
                if full.exists():
                    full.unlink()
                    edit_entry["status"] = "deleted"

            edits.append(edit_entry)

        return {
            "deliverable": filename,
            "project": project,
            "dry_run": dry_run,
            "task_count": len(tasks),
            "edits": edits,
        }

    def workspace_tree(self, max_depth: int = 3) -> str:
        """Return workspace directory tree as text.

        Parameters
        ----------
        max_depth : int
            Maximum directory traversal depth (default: 3).

        Returns
        -------
        str
            Text representation of the workspace directory tree.

        """
        if not self.workspace.exists():
            return f"Workspace not found: {self.workspace}"

        lines = [f"Workspace: {self.workspace}", ""]
        skip = {
            "node_modules", "__pycache__", ".git", ".svn", "dist",
            "build", ".venv", "venv", ".vectordb", ".idea", ".vscode",
        }
        self._tree_recursive(self.workspace, lines, "", skip, max_depth)
        return "\n".join(lines)

    def _tree_recursive(
        self,
        path: Path,
        lines: list[str],
        prefix: str,
        skip: set[str],
        max_depth: int,
        depth: int = 0,
    ) -> None:
        """Recursively build the directory tree text.

        Parameters
        ----------
        path : Path
            Current directory path.
        lines : list[str]
            Accumulator list for tree lines.
        prefix : str
            Current indentation prefix.
        skip : set[str]
            Directory names to skip.
        max_depth : int
            Maximum traversal depth.
        depth : int
            Current recursion depth.

        """
        if depth >= max_depth:
            return
        try:
            entries = sorted(
                path.iterdir(),
                key=lambda e: (not e.is_dir(), e.name.lower()),
            )
        except PermissionError:
            return
        entries = [
            e for e in entries
            if not e.name.startswith(".") and e.name not in skip
        ]
        for i, entry in enumerate(entries):
            is_last = i == len(entries) - 1
            connector = "\u2514\u2500\u2500 " if is_last else "\u251c\u2500\u2500 "
            icon = "\U0001f4c1" if entry.is_dir() else "\U0001f4c2"
            lines.append(f"{prefix}{connector}{icon} {entry.name}")
            if entry.is_dir():
                ext = "    " if is_last else "\u2502   "
                self._tree_recursive(entry, lines, prefix + ext, skip, max_depth, depth + 1)


# ---------------------------------------------------------------------------
# Module‑level import of discover_tools for convenience.
# ---------------------------------------------------------------------------
from src.mcp.registry import discover_tools  # noqa: E402
