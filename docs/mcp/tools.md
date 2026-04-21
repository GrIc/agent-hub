# Agent Hub — MCP Tools Reference

> Auto-generated reference for all MCP tools exposed by Agent Hub.

**Note:** This file will be auto-generated in Phase 4. This is a placeholder with the expected structure.

## Tool Categories

### 1. Code Intelligence Tools

| Tool | Description | Input Schema | Output Schema |
|------|-------------|--------------|---------------|
| `expert_ask` | RAG-powered code Q&A with full hybrid search | `query: str` | `answer: str, sources: [{path, line_start, line_end, score, text}]` |
| `search_rag` | Search the vector index directly | `query: str, top_k: int?` | `results: [{source, text, score}]` |
| `search_graph` | Query the knowledge graph for entity relationships | `query: str` | `nodes: [...], edges: [...], sources: [...]` |

### 2. File Operations Tools

| Tool | Description | Input Schema | Output Schema |
|------|-------------|--------------|---------------|
| `read_file` | Read a file from the workspace | `path: str` | `content: str, sources: [...]` |
| `edit_file` | Write/overwrite a file in the workspace | `path: str, content: str` | `success: bool, sources: [...]` |

### 3. Project Management Tools

| Tool | Description | Input Schema | Output Schema |
|------|-------------|--------------|---------------|
| `list_deliverables` | List project deliverables (specs, roadmaps…) | `project_name?: str` | `deliverables: [{name, type, version, path}]` |
| `read_deliverable` | Read a specific deliverable's content | `project_name: str, deliverable_name: str` | `content: str, sources: [...]` |
| `apply_deliverable` | Apply a deliverable automatically (dry-run or live) | `project_name: str, deliverable_name: str, mode: "dry-run"\|"live"` | `changes: [...], applied: bool, sources: [...]` |

### 4. Documentation Tools

| Tool | Description | Input Schema | Output Schema |
|------|-------------|--------------|---------------|
| `list_wiki_pages` | List all wiki pages | `query?: str` | `pages: [{title, path, last_updated}]` |
| `read_wiki_page` | Read a wiki page | `title: str` | `content: str, sources: [...]` |
| `update_wiki_page` | Update or create a wiki page | `title: str, content: str, message?: str` | `success: bool, url: str, sources: [...]` |

### 5. Analysis Tools

| Tool | Description | Input Schema | Output Schema |
|------|-------------|--------------|---------------|
| `call_graph` | Generate call graph for a function/class | `target: str, depth: int?` | `nodes: [...], edges: [...], sources: [...]` |
| `impact_preview` | Preview impact of changes | `targets: [str], change_type: "refactor"\|"feature"\|"fix"` | `impacted_components: [...], risk_score: float, sources: [...]` |
| `discover_patterns` | Discover team-specific patterns and idioms | `pattern_type?: "naming"\|"structure"\|"convention"` | `patterns: [...], examples: [...], sources: [...]` |
| `discover_conventions` | Discover team conventions | `domain?: str` | `conventions: [...], violations: [...], sources: [...]` |

### 6. Discovery Tools

| Tool | Description | Input Schema | Output Schema |
|------|-------------|--------------|---------------|
| `list_tools` | List all available MCP tools | `{}` | `tools: [{name, description, input_schema, output_schema}]` |
| `get_tool_schema` | Get schema for a specific tool | `tool_name: str` | `schema: {...}` |
| `ping` | Health check and tool availability | `{}` | `status: "ok"\|"degraded", tools_available: int, latency_ms: int` |

### 7. Utility Tools

| Tool | Description | Input Schema | Output Schema |
|------|-------------|--------------|---------------|
| `get_config` | Get current configuration | `path?: str` | `config: {...}` |
| `set_config` | Update configuration | `path: str, value: any` | `success: bool, previous_value: any` |
| `list_resources` | List available resources | `{}` | `resources: [{uri, name, mime_type}]` |
| `read_resource` | Read a resource | `uri: str` | `content: str, mime_type: str` |

## Input/Output Contract

### Citation Contract

Every tool that returns code-related information **MUST** include a `sources` field:

```json
{
  "sources": [
    {
      "path": "src/services/user_service.py",
      "line_start": 42,
      "line_end": 67,
      "score": 0.95,
      "text": "...snippet..."
    }
  ]
}
```

### Grounding Validation

Tools must validate that all referenced names exist in the source:
- Class names
- Method names
- File paths
- Module names
- Variable names

If validation fails, return `INSUFFICIENT_EVIDENCE` with empty result and explanatory note.

## Tool Discovery

Clients can discover available tools via:

```bash
# MCP SSE endpoint
curl http://localhost:8080/mcp/sse | grep "tool/"

# Or via MCP client library
```

## Performance Characteristics

| Tool | Typical Latency | Memory Usage | Notes |
|------|----------------|--------------|-------|
| `expert_ask` | 1–3s | 50–200MB | Depends on LLM and index size |
| `search_rag` | 200–500ms | 10–50MB | ChromaDB query |
| `search_graph` | 300–800ms | 20–100MB | Graph traversal |
| `read_file` | 10–50ms | 1–10MB | Filesystem read |
| `edit_file` | 50–200ms | 5–50MB | Filesystem write |
| `list_deliverables` | 50–100ms | 5–20MB | Filesystem scan |

## Error Handling

All tools return structured errors:

```json
{
  "error": {
    "type": "invalid_input"\|"not_found"\|"insufficient_evidence"\|"tool_error",
    "message": "Human-readable description",
    "details": {...}
  }
}
```

### Common Error Types

- `invalid_input`: Input validation failed (schema mismatch)
- `not_found`: Requested resource doesn't exist
- `insufficient_evidence`: Cannot ground answer in source
- `tool_error`: Tool-specific failure (filesystem, LLM, etc.)


## Testing

Each tool must include:
- Unit tests for input validation
- Integration tests for happy path
- Error scenario tests
- Golden tests for output structure

**See:** [`src/mcp_server.py`](src/mcp_server.py) for tool implementations

---

**Next:** [Client Setup Instructions](docs/clients/) | [Operations Guide](docs/operations/)
