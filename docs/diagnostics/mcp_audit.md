# MCP Server Audit Report

**File audited:** [`src/mcp_server.py`](src/mcp_server.py)  
**Date:** 2026-05-10  
**Scope:** T-401 — Pre-implementation diagnostic audit of the existing MCP server

---

## Summary

The MCP server at `src/mcp_server.py` exposes **7 tools** and **1 resource** via the MCP SDK. All tools are defined inline in the `create_mcp_server()` factory function using the legacy `Server` API (not the newer `BaseTool` framework). The server uses a monolithic `AgentHubBridge` class to route tool calls to implementation methods.

---

## Tool Inventory

### 1. `expert_ask`

| Attribute | Value |
|-----------|-------|
| **Input Schema** | `{"type": "object", "properties": {"question": {"type": "string", "description": "Your question about the codebase"}}, "required": ["question"]}` |
| **Output Schema** | None declared; returns `TextContent` wrapping the raw string response from `expert.chat()` |
| **Failure Modes** | • No input validation on `question` (empty string, overly long input)<br>• `expert.chat()` can raise exceptions; caught by the outer `try/except` in `call_tool` but returns a generic `"Error: {e}"` string<br>• No citation/source tracking — the expert agent returns free-text with no structured citations<br>• No timeout on the LLM call — could hang indefinitely |
| **Latency** | High (LLM call via `asyncio.to_thread`). No explicit timeout. Typical LLM latency: 5–30s depending on model and RAG context size |

### 2. `search_rag`

| Attribute | Value |
|-----------|-------|
| **Input Schema** | `{"type": "object", "properties": {"query": {"type": "string"}, "top_k": {"type": "integer", "default": 8}}, "required": ["query"]}` |
| **Output Schema** | None declared; returns `TextContent` wrapping JSON-serialized list of dicts with keys: `text`, `source`, `score`, `doc_level` |
| **Failure Modes** | • No validation on `query` (empty string)<br>• `top_k` accepts any integer — no upper bound enforcement<br>• No citation validation on returned chunks<br>• Returns raw JSON string — no structured output schema |
| **Latency** | Medium (hybrid vector + rerank search). No explicit timeout. Typical: 1–5s |

### 3. `search_graph`

| Attribute | Value |
|-----------|-------|
| **Input Schema** | `{"type": "object", "properties": {"entity": {"type": "string"}, "max_hops": {"type": "integer", "default": 2}}, "required": ["entity"]}` |
| **Output Schema** | None declared; returns `TextContent` wrapping JSON-serialized dict with keys: `entity`, `matches`, `neighbor_count`, `summary`, `stats` |
| **Failure Modes** | • No validation on `entity` (empty string)<br>• `max_hops` accepts any integer — no upper bound<br>• Creates a new `KnowledgeGraph` instance per call (line 166) — no caching, redundant disk I/O<br>• Returns error dict as JSON text rather than using MCP error responses |
| **Latency** | Medium-High (graph traversal + BFS). No explicit timeout. Typical: 1–10s depending on graph size |

### 4. `read_file`

| Attribute | Value |
|-----------|-------|
| **Input Schema** | `{"type": "object", "properties": {"filepath": {"type": "string", "description": "Relative path from workspace root"}}, "required": ["filepath"]}` |
| **Output Schema** | None declared; returns `TextContent` wrapping file content string (or error message) |
| **Failure Modes** | • Path traversal protection exists (line 196) but uses deprecated `is_relative_to()` — will break on Python 3.12+<br>• No file size limit — could return multi-MB files as a single string<br>• No content-type detection<br>• Error returned as text prefix `"Error: ..."` rather than MCP structured error |
| **Latency** | Low (file I/O). Typical: <100ms for small files |

### 5. `edit_file`

| Attribute | Value |
|-----------|-------|
| **Input Schema** | `{"type": "object", "properties": {"filepath": {"type": "string"}, "content": {"type": "string"}}, "required": ["filepath", "content"]}` |
| **Output Schema** | None declared; returns `TextContent` wrapping JSON-serialized dict with keys: `filepath`, `status`, `size` (or `error`) |
| **Failure Modes** | • Path traversal protection exists (line 213)<br>• No content validation (can write arbitrary bytes)<br>• No backup/undo mechanism<br>• No file size limit<br>• Atomicity: if `mkdir` succeeds but `write_text` fails, partial state remains |
| **Latency** | Low (file I/O). Typical: <100ms |

### 6. `list_deliverables`

| Attribute | Value |
|-----------|-------|
| **Input Schema** | `{"type": "object", "properties": {"project": {"type": "string", "description": "Project name"}}, "required": ["project"]}` |
| **Output Schema** | None declared; returns `TextContent` wrapping JSON-serialized list of dicts |
| **Failure Modes** | • No validation on `project` (empty string, path traversal via `../`)<br>• Returns empty list `[]` silently when project dir doesn't exist — no error indication<br>• Regex parsing of filenames (line 236) is fragile — only handles `*_v{N}.md` pattern |
| **Latency** | Low (directory listing). Typical: <50ms |

### 7. `read_deliverable`

| Attribute | Value |
|-----------|-------|
| **Input Schema** | `{"type": "object", "properties": {"project": {"type": "string"}, "filename": {"type": "string", "description": "Deliverable filename"}}, "required": ["project", "filename"]}` |
| **Output Schema** | None declared; returns `TextContent` wrapping file content or error message |
| **Failure Modes** | • No path traversal protection on `filename` — `../../etc/passwd` could escape the deliverables directory<br>• No file size limit<br>• Error returned as text prefix rather than MCP structured error |
| **Latency** | Low (file I/O). Typical: <100ms |

### 8. `apply_deliverable` (Killer Feature)

| Attribute | Value |
|-----------|-------|
| **Input Schema** | `{"type": "object", "properties": {"project": {"type": "string"}, "filename": {"type": "string"}, "dry_run": {"type": "boolean", "default": true}}, "required": ["project", "filename"]}` |
| **Output Schema** | None declared; returns `TextContent` wrapping JSON-serialized dict with keys: `deliverable`, `project`, `dry_run`, `task_count`, `edits` |
| **Failure Modes** | • **Most complex tool** — chains multiple LLM calls (analysis + per-task edit generation)<br>• No input validation on `project` or `filename`<br>• No path traversal protection on `filename`<br>• JSON extraction from LLM output uses fragile regex (line 321-324)<br>• No rate limiting between chained LLM calls<br>• No cancellation support for long-running multi-step operations<br>• Existing content capped at 8000 chars (line 370) — arbitrary limit<br>• No progress reporting during multi-task execution<br>• If `dry_run=false`, files are written without confirmation or rollback |
| **Latency** | Very High (multiple sequential LLM calls). No timeout. Typical: 30s–5min+ depending on task count |

---

## Resource Inventory

### `workspace://tree`

| Attribute | Value |
|-----------|-------|
| **Description** | Directory tree of the indexed codebase |
| **Failure Modes** | • No depth limit enforcement beyond `max_depth` parameter<br>• Skips hidden files and common build dirs, but no configurable exclusions |
| **Latency** | Low-Medium (recursive directory walk). Typical: <500ms |

---

## Overall Observations

### 1. No Structured Output Schemas
None of the 7 tools declare an `outputSchema`. All return `TextContent` wrapping either plain text or JSON strings. This means MCP clients cannot validate responses programmatically.

### 2. No Citation Tracking
Per the grounding requirements, tools that return code/info should set `requires_citations=True` and populate sources. None of the current tools do this. `search_rag` returns `source` fields but they are not structured as MCP citations.

### 3. No Input Validation
Most tools accept raw string inputs without any validation (empty strings, path traversal, length limits). The only protection is the path traversal check in `read_file` and `edit_file`, which itself uses deprecated Python APIs.

### 4. Error Handling Inconsistency
- Some tools return `{"error": "..."}` dicts (e.g., `read_file`, `edit_file`)
- The `call_tool` handler converts these to `"Error: ..."` text prefixes
- Other tools (e.g., `search_graph`) return error dicts as JSON text
- No use of MCP's native error response mechanism

### 5. No Timeout Configuration
No tool has an explicit timeout. LLM-bound tools (`expert_ask`, `apply_deliverable`) can hang indefinitely.

### 6. Code Duplication
- Path traversal checks are duplicated in `read_file` and `edit_file`
- JSON serialization with `indent=2, ensure_ascii=False` is repeated across all tool handlers
- Error wrapping pattern is inconsistent

### 7. No Middleware / Interceptor Layer
There is no middleware for:
- Request logging/metrics
- Rate limiting
- Authentication/authorization
- Request/response transformation

### 8. No MCP Tool Registration Framework
Tools are defined inline in `create_mcp_server()` rather than using the `BaseTool` framework with input/output schemas. This makes it difficult to:
- Share tool implementations across servers
- Auto-generate documentation
- Validate inputs/outputs consistently

### 9. Lazy Agent Initialization
The expert agent is lazily initialized on first use. Subsequent calls reuse the same instance, but there is no cleanup mechanism.

### 10. Graph Instance Per Call
`search_graph` creates a new `KnowledgeGraph` instance on every call (line 166), causing redundant disk I/O. A cached or singleton instance would be more efficient.

---

## Risk Summary

| Risk | Severity | Tools Affected |
|------|----------|----------------|
| No input validation | High | All 7 tools |
| No timeout | High | `expert_ask`, `apply_deliverable` |
| Path traversal (partial protection) | High | `read_deliverable`, `list_deliverables` |
| No citation tracking | Medium | `search_rag`, `search_graph`, `expert_ask` |
| No output schema | Medium | All 7 tools |
| Fragile JSON parsing | Medium | `apply_deliverable` |
| No rate limiting | Medium | `apply_deliverable` |
| No rollback on write | Low | `edit_file`, `apply_deliverable` |

---

## Recommendations for T-402 Through T-407

1. **T-402**: Refactor all tools to use the `BaseTool` framework with strict input/output schemas
2. **T-403**: Add input validation (pydantic models) for all tool inputs
3. **T-404**: Implement citation tracking for tools returning code/info
4. **T-405**: Add timeout configuration per tool
5. **T-406**: Implement middleware for logging, metrics, and rate limiting
6. **T-407**: Add path traversal protection to all file-access tools
