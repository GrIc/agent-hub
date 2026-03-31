"""
MCP (Model Context Protocol) server for Agent Hub.

Exposes Agent Hub capabilities as MCP tools that any compatible IDE client
can call: VS Code (Continue, Cline, Copilot), IntelliJ (JetBrains AI),
Claude Code, or any other MCP-compatible client.

Transport: SSE (Server-Sent Events) over HTTP, mounted on the existing
FastAPI app at /mcp.

Tools exposed:
  - expert_ask       : Ask the expert agent a question (with full RAG context)
  - search_rag       : Direct RAG search (returns raw chunks)
  - read_file        : Read a workspace file
  - edit_file        : Write/overwrite a workspace file
  - list_deliverables: List pipeline deliverables for a project
  - read_deliverable : Read a deliverable's content
  - apply_deliverable: Parse a spec and generate file edits (the killer feature)

Resources exposed:
  - workspace://tree         : Workspace file tree
  - project://{name}/status  : Project status (notes, outputs, reports)

Usage:
  # Standalone (for development / debugging):
  python -m src.mcp_server

  # Integrated with FastAPI (production):
  # The server.py create_app() mounts the MCP SSE endpoint at /mcp
"""

import asyncio
import json
import logging
import re
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports — mcp SDK is optional, installed only when IDE features are used
# ---------------------------------------------------------------------------

def _check_mcp_sdk():
    try:
        import mcp  # noqa: F401
        return True
    except ImportError:
        logger.error(
            "MCP SDK not installed. Run: pip install mcp[server] --break-system-packages"
        )
        return False


# ---------------------------------------------------------------------------
# Core: Agent Hub integration layer
# ---------------------------------------------------------------------------

class AgentHubBridge:
    """
    Thin bridge between MCP tool calls and Agent Hub internals.
    Reuses the same ResilientClient, VectorStore, and agent instances
    that the web UI and CLI use.
    """

    def __init__(self, cfg: dict):
        from src.client import ResilientClient
        from src.rag.store import VectorStore
        from src.config import (
            get_model_for_agent,
            get_agent_temperature,
            get_agent_extra_params,
            build_custom_dsl_context,
            build_domain_context,
        )
        from src.agent_defs import load_agent_definition

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

        self.dsl_context = build_custom_dsl_context(cfg)
        self.domain_context = build_domain_context(cfg)

        # Lazily initialized agents
        self._expert = None
        self._developer = None

    def _get_expert(self):
        """Lazy-init the expert agent."""
        if self._expert is None:
            from src.agents.base import BaseAgent
            from src.config import get_model_for_agent, get_agent_temperature, get_agent_extra_params

            class ExpertMCP(BaseAgent):
                name = "expert"

            self._expert = ExpertMCP(
                client=self.client,
                store=self.store,
                model=get_model_for_agent(self.cfg, "expert"),
                temperature=get_agent_temperature(self.cfg, "expert"),
                rag_top_k=self.cfg.get("rag", {}).get("top_k", 8),
                custom_dsl_info=self.dsl_context,
                domain_info=self.domain_context,
                extra_params=get_agent_extra_params(self.cfg, "expert"),
            )
        return self._expert

    def _get_developer(self):
        """Lazy-init the developer agent."""
        if self._developer is None:
            from src.agents.developer import DeveloperAgent
            from src.config import get_model_for_agent, get_agent_temperature, get_agent_extra_params

            self._developer = DeveloperAgent(
                client=self.client,
                store=self.store,
                model=get_model_for_agent(self.cfg, "developer"),
                temperature=get_agent_temperature(self.cfg, "developer"),
                rag_top_k=self.cfg.get("rag", {}).get("top_k", 8),
                custom_dsl_info=self.dsl_context,
                domain_info=self.domain_context,
                extra_params=get_agent_extra_params(self.cfg, "developer"),
                workspace_path=str(self.workspace),
            )
        return self._developer

    # -- Tool implementations -----------------------------------------------

    def expert_ask(self, question: str) -> str:
        """Ask the expert agent a question with full RAG context."""
        expert = self._get_expert()
        response = expert.chat(question)
        return response

    def search_rag(self, query: str, top_k: int = 8) -> list[dict]:
        """Direct RAG search, returns raw chunks with scores."""
        results = self.store.search_hierarchical(query, top_k=top_k)
        return [
            {
                "text": r["text"],
                "source": r["source"],
                "score": round(r.get("rerank_score", r.get("score", 0)), 4),
                "doc_level": r.get("doc_level", ""),
            }
            for r in results
        ]

    def read_file(self, filepath: str) -> dict:
        """Read a file from the workspace."""
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
        """Write content to a workspace file. Creates parent dirs if needed."""
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
        """List all pipeline deliverables for a project."""
        from src.projects import get_or_create_project
        project_dir = Path("projects") / project / "outputs"
        if not project_dir.exists():
            return []

        deliverables = []
        for f in sorted(project_dir.glob("*.md"), reverse=True):
            # Parse type and version from filename: specifications_v3.md
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
        """Read a specific deliverable file."""
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
        """
        Parse a pipeline deliverable (e.g., specifier output) and generate
        file edits. This is the killer feature.

        Workflow:
        1. Read the deliverable markdown
        2. Extract actionable tasks/changes (sections with file paths, code blocks)
        3. For each task: use expert (RAG) to understand existing code,
           then developer to generate the edit
        4. Return a list of proposed edits (file path + new content)

        In dry_run mode (default), returns proposed edits without applying.
        When dry_run=False, writes the files directly.
        """
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

        developer = self._get_developer()

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
        edits = []
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
            rag_context = self.search_rag(
                f"{filepath} {description}", top_k=4
            )
            rag_text = "\n---\n".join(r["text"][:500] for r in rag_context)

            # Ask the developer agent to generate the new file content
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
                edit_response = developer.chat(edit_prompt)
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

        # Reset agent histories to avoid token accumulation across tasks
        expert.history.clear()
        developer.history.clear()

        return {
            "deliverable": filename,
            "project": project,
            "dry_run": dry_run,
            "task_count": len(tasks),
            "edits": edits,
        }

    def workspace_tree(self, max_depth: int = 3) -> str:
        """Return workspace directory tree as text."""
        if not self.workspace.exists():
            return f"Workspace not found: {self.workspace}"

        lines = [f"Workspace: {self.workspace}", ""]
        skip = {
            "node_modules", "__pycache__", ".git", ".svn", "dist",
            "build", ".venv", "venv", ".vectordb", ".idea", ".vscode",
        }
        self._tree_recursive(self.workspace, lines, "", skip, max_depth)
        return "\n".join(lines)

    def _tree_recursive(self, path, lines, prefix, skip, max_depth, depth=0):
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
            connector = "└── " if is_last else "├── "
            icon = "📁" if entry.is_dir() else "📄"
            lines.append(f"{prefix}{connector}{icon} {entry.name}")
            if entry.is_dir():
                ext = "    " if is_last else "│   "
                self._tree_recursive(
                    entry, lines, prefix + ext, skip, max_depth, depth + 1
                )


# ---------------------------------------------------------------------------
# MCP Server definition
# ---------------------------------------------------------------------------

def create_mcp_server(cfg: dict):
    """
    Create and configure the MCP server instance.
    Returns the Server object (from the mcp SDK).
    """
    if not _check_mcp_sdk():
        return None

    from mcp.server import Server
    from mcp.types import (
        Tool,
        TextContent,
        Resource,
        ResourceTemplate,
    )

    bridge = AgentHubBridge(cfg)
    server = Server("agent-hub")

    # -- Tool definitions ---------------------------------------------------

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="expert_ask",
                description=(
                    "Ask the Agent Hub expert agent a question about the codebase. "
                    "Uses RAG (hierarchical search over documentation and source code) "
                    "to provide accurate, contextual answers. Good for: understanding "
                    "how code works, debugging, architecture questions, code review."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "Your question about the codebase",
                        },
                    },
                    "required": ["question"],
                },
            ),
            Tool(
                name="search_rag",
                description=(
                    "Search the Agent Hub RAG index directly. Returns raw document "
                    "chunks with relevance scores. Use this when you need specific "
                    "code snippets or documentation fragments rather than a conversational answer."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query (keywords or natural language)",
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Number of results (default: 8)",
                            "default": 8,
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="read_file",
                description=(
                    "Read a file from the workspace (the codebase indexed by Agent Hub). "
                    "Returns the file content as text."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "filepath": {
                            "type": "string",
                            "description": "Relative path from workspace root",
                        },
                    },
                    "required": ["filepath"],
                },
            ),
            Tool(
                name="edit_file",
                description=(
                    "Write content to a file in the workspace. Creates parent "
                    "directories if needed. Use this to implement code changes."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "filepath": {
                            "type": "string",
                            "description": "Relative path from workspace root",
                        },
                        "content": {
                            "type": "string",
                            "description": "Full file content to write",
                        },
                    },
                    "required": ["filepath", "content"],
                },
            ),
            Tool(
                name="list_deliverables",
                description=(
                    "List all pipeline deliverables for an Agent Hub project. "
                    "Deliverables are versioned markdown files generated by the "
                    "pipeline agents (requirements, specifications, roadmap, etc.)."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project name",
                        },
                    },
                    "required": ["project"],
                },
            ),
            Tool(
                name="read_deliverable",
                description=(
                    "Read a specific pipeline deliverable. Use after list_deliverables "
                    "to get the content of a requirements, specifications, or roadmap file."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project name",
                        },
                        "filename": {
                            "type": "string",
                            "description": "Deliverable filename (e.g. specifications_v2.md)",
                        },
                    },
                    "required": ["project", "filename"],
                },
            ),
            Tool(
                name="apply_deliverable",
                description=(
                    "THE KILLER FEATURE. Parse a pipeline deliverable (typically a "
                    "specifier or planner output) and automatically generate file edits "
                    "to implement all the specified changes. In dry_run mode (default), "
                    "returns proposed edits for review. Set dry_run=false to apply directly."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project name",
                        },
                        "filename": {
                            "type": "string",
                            "description": "Deliverable filename to implement",
                        },
                        "dry_run": {
                            "type": "boolean",
                            "description": "If true (default), only propose edits. If false, apply them.",
                            "default": True,
                        },
                    },
                    "required": ["project", "filename"],
                },
            ),
        ]

    # -- Tool call handler --------------------------------------------------

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        """Route tool calls to the bridge."""
        try:
            if name == "expert_ask":
                result = await asyncio.to_thread(
                    bridge.expert_ask, arguments["question"]
                )
                return [TextContent(type="text", text=result)]

            elif name == "search_rag":
                results = await asyncio.to_thread(
                    bridge.search_rag,
                    arguments["query"],
                    arguments.get("top_k", 8),
                )
                return [TextContent(
                    type="text",
                    text=json.dumps(results, indent=2, ensure_ascii=False),
                )]

            elif name == "read_file":
                result = await asyncio.to_thread(
                    bridge.read_file, arguments["filepath"]
                )
                if "error" in result:
                    return [TextContent(type="text", text=f"Error: {result['error']}")]
                return [TextContent(type="text", text=result["content"])]

            elif name == "edit_file":
                result = await asyncio.to_thread(
                    bridge.edit_file,
                    arguments["filepath"],
                    arguments["content"],
                )
                return [TextContent(
                    type="text",
                    text=json.dumps(result, indent=2),
                )]

            elif name == "list_deliverables":
                results = await asyncio.to_thread(
                    bridge.list_deliverables, arguments["project"]
                )
                return [TextContent(
                    type="text",
                    text=json.dumps(results, indent=2, ensure_ascii=False),
                )]

            elif name == "read_deliverable":
                result = await asyncio.to_thread(
                    bridge.read_deliverable,
                    arguments["project"],
                    arguments["filename"],
                )
                if "error" in result:
                    return [TextContent(type="text", text=f"Error: {result['error']}")]
                return [TextContent(type="text", text=result["content"])]

            elif name == "apply_deliverable":
                result = await asyncio.to_thread(
                    bridge.apply_deliverable,
                    arguments["project"],
                    arguments["filename"],
                    arguments.get("dry_run", True),
                )
                return [TextContent(
                    type="text",
                    text=json.dumps(result, indent=2, ensure_ascii=False),
                )]

            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

        except Exception as e:
            logger.exception(f"Tool {name} failed")
            return [TextContent(type="text", text=f"Error: {e}")]

    # -- Resources ----------------------------------------------------------

    @server.list_resources()
    async def list_resources() -> list[Resource]:
        from pydantic import AnyUrl
        return [
            Resource(
                uri=AnyUrl("workspace://tree"),
                name="Workspace file tree",
                mimeType="text/plain",
                description="Directory tree of the indexed codebase",
            ),
        ]

    @server.read_resource()
    async def read_resource(uri) -> str:
        if str(uri) == "workspace://tree":
            return await asyncio.to_thread(bridge.workspace_tree)
        return f"Unknown resource: {uri}"

    return server


# ---------------------------------------------------------------------------
# SSE transport integration for FastAPI
# ---------------------------------------------------------------------------

def mount_mcp_sse(app, cfg: dict):
    """
    Mount the MCP server as an SSE endpoint on an existing FastAPI app.
    Clients connect to:  GET /mcp/sse  (event stream)
    and send requests to: POST /mcp/messages  (JSON-RPC)
    """
    if not _check_mcp_sdk():
        logger.warning("MCP SDK not available — IDE integration disabled")
        return

    from mcp.server.sse import SseServerTransport
    from starlette.routing import Route, Mount

    server = create_mcp_server(cfg)
    if server is None:
        return

    sse_transport = SseServerTransport("/mcp/messages")

    async def handle_sse(request):
        """Handle SSE connection from IDE client."""
        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await server.run(
                streams[0],
                streams[1],
                server.create_initialization_options(),
            )

    async def handle_messages(request):
        """Handle JSON-RPC messages from IDE client."""
        return await sse_transport.handle_post_message(
            request.scope, request.receive, request._send
        )

    # Mount as sub-application
    app.mount(
        "/mcp",
        Mount(
            "/mcp",
            routes=[
                Route("/sse", endpoint=handle_sse),
                Route("/messages", endpoint=handle_messages, methods=["POST"]),
            ],
        ),
    )
    logger.info("MCP SSE endpoint mounted at /mcp/sse")


# ---------------------------------------------------------------------------
# Standalone mode (for development)
# ---------------------------------------------------------------------------

def main():
    """Run MCP server standalone with stdio transport (for local IDE testing)."""
    if not _check_mcp_sdk():
        sys.exit(1)

    from src.config import load_config
    from mcp.server.stdio import stdio_server

    logging.basicConfig(level=logging.INFO)
    cfg = load_config()

    server = create_mcp_server(cfg)
    if server is None:
        sys.exit(1)

    print("Agent Hub MCP server starting (stdio transport)...", file=sys.stderr)

    async def run():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

    asyncio.run(run())


if __name__ == "__main__":
    main()
