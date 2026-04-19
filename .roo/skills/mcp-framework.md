# Skill: MCP Framework

> Loaded by: `mcp-engineer`.
> Purpose: concrete patterns for building well-behaved MCP tools in this repo.

---

## 1. Anatomy of a tool file

Every tool lives in `src/mcp/tools/<tool_name>.py`. Skeleton:

```python
"""MCP tool: <one-line purpose>."""

from src.mcp.base import BaseTool, ToolError

class <ToolName>Tool(BaseTool):
    name = "<snake_case_name>"
    description = "One sentence for MCP list_tools."
    input_schema = {
        "type": "object",
        "properties": {
            # ... JSON Schema for each input
        },
        "required": ["..."],
        "additionalProperties": False,
    }
    output_schema = {
        "type": "object",
        "properties": {
            # ... JSON Schema for each output
            "sources": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "line_start": {"type": "integer", "minimum": 1},
                        "line_end": {"type": "integer", "minimum": 1},
                    },
                    "required": ["path", "line_start", "line_end"],
                },
            },
        },
        "required": [...],  # always include "sources" if requires_citations
        "additionalProperties": False,
    }
    examples = [
        {"input": {...}, "output": {...}},
    ]
    requires_citations = True   # default True; set False only with justification
    auth_required = False       # True for admin tools
    rate_limit_per_minute = 60

    def __init__(self, *, rag_store, graph_store, temporal_store, config):
        # injected at registry time
        self.rag = rag_store
        self.graph = graph_store
        self.temporal = temporal_store
        self.config = config

    def handle(self, args: dict) -> dict:
        # implementation here
        ...
```

The registry (`src/mcp/registry.py`) auto-discovers all `BaseTool` subclasses in `src/mcp/tools/` and instantiates them with the dependency bundle.

---

## 2. Input schema discipline

**Be strict**. Use:

- `"additionalProperties": false` always — reject unknown keys.
- `"required": [...]` for every truly mandatory input.
- `"enum": [...]` for bounded choices (`doc_level`, `language`, etc.).
- `"maximum"` / `"maxLength"` to prevent pathological inputs.
- `"default": ...` only in your Python code, not in the schema itself (JSON Schema defaults don't auto-populate — the framework passes missing values as `None`).

---

## 3. Output schema discipline

**Be strict** and **include sources**. Example for a semantic search tool:

```json
{
  "type": "object",
  "properties": {
    "results": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "snippet": {"type": "string", "maxLength": 2000},
          "score": {"type": "number"},
          "source": {
            "type": "object",
            "properties": {
              "path": {"type": "string"},
              "line_start": {"type": "integer"},
              "line_end": {"type": "integer"}
            },
            "required": ["path", "line_start", "line_end"]
          }
        },
        "required": ["snippet", "score", "source"]
      }
    },
    "notes": {"type": "string"},
    "sources": {"type": "array", ... }
  },
  "required": ["results", "sources"],
  "additionalProperties": false
}
```

`sources` at the top level is the **flat list the citation middleware validates**. Individual `source` fields within items are for the caller's UX. Both are OK; duplication is fine.

---

## 4. Citation contract — the hard part

If `requires_citations = True`:

1. Every top-level `sources` entry must have: `path` (exists on disk), `line_start`, `line_end`.
2. The middleware reads the cited file ranges.
3. If the output contains `identifiers_mentioned` or names extracted from prose, each one must appear in the cited range.
4. `line_end - line_start ≤ 200` — no "see the whole file" citations.
5. An empty `sources` list is allowed ONLY if accompanied by a `notes` field explaining why.

**To avoid citation failures**:

- Build `sources` from chunks/nodes that have explicit `line_start` / `line_end` metadata (Phase 1 T-106 added these).
- Never fabricate ranges. If the chunk has `line_start=150`, use 150, not "around line 150".
- If summarizing 20 chunks, cite the top 3-5, not all 20 (user gets the signal, middleware avoids slow I/O).

---

## 5. Error handling

Use `ToolError` for recoverable errors (caller can retry or adjust input):

```python
if module not in self.graph.all_module_names():
    raise ToolError("not_found", f"module '{module}' does not exist",
                    hint="call list_modules to see available modules")
```

For unexpected exceptions, let them propagate — `BaseTool.__call__` turns them into `internal_error`.

**Never return 500s**. Every error path returns a structured envelope. Consumers (Cline, Roo) will read `error.code` and `error.hint`; a 500 leaves them blind.

---

## 6. Golden tests

Each tool ships a golden test in `tests/golden/test_mcp_tools.py`:

```python
def test_find_code_happy_path(mini_workspace_tool_set):
    tool = mini_workspace_tool_set["find_code"]
    result = tool({"intent": "authentication", "top_k": 3}, context={})
    assert "results" in result
    assert len(result["results"]) >= 1
    assert all("path" in r["source"] for r in result["results"])

def test_find_code_citation_contract(mini_workspace_tool_set):
    tool = mini_workspace_tool_set["find_code"]
    result = tool({"intent": "auth", "top_k": 3}, context={})
    for src in result.get("sources", []):
        assert Path("workspace") / src["path"] exists
        assert src["line_start"] <= src["line_end"]

def test_find_code_invalid_input(mini_workspace_tool_set):
    tool = mini_workspace_tool_set["find_code"]
    result = tool({"intent": "x" * 10000}, context={})  # over length limit
    assert result.get("error", {}).get("code") == "invalid_input"
```

Use a fixture `mini_workspace_tool_set` that builds the small workspace from `tests/fixtures/mini_workspace/` and instantiates all tools against it.

---

## 7. Auto-docs

After adding a tool, run `python scripts/build_mcp_docs.py` to regenerate `docs/mcp/tools.md`. Commit the regenerated doc. The CI pipeline can enforce this with:

```yaml
- script:
  - python scripts/build_mcp_docs.py
  - git diff --exit-code docs/mcp/tools.md  # fail if outdated
```

---

## 8. Naming

- Tool names are `snake_case`, verb-first when imperative (`find_code`, `get_callers`, `run_pipeline`).
- `get_*` for reads, `list_*` for enumerations, `find_*` for search.
- No tool starts with a negative: `no_*`, `skip_*`, etc.

---

## 9. Rate limiting

Each tool sets `rate_limit_per_minute`. Guidelines:

| Tool class | Limit |
|------------|-------|
| Cheap reads (`list_tools`, `get_coverage_report`) | 120 |
| Graph reads (`get_callers`, `shortest_path`) | 60 |
| RAG reads (`find_code`, `ask_expert`) | 30 |
| LLM-heavy (`get_architecture_blueprint`, `run_pipeline`) | 10 |
| Admin writes (`reindex`) | 3 |

Override in `config.yaml: mcp.rate_limit.per_tool`.

---

## 10. Anti-patterns

| Smell | Fix |
|-------|-----|
| Tool returns free-form Markdown that names files | Return structured JSON with explicit `sources`. The caller formats prose. |
| Tool calls another tool internally via HTTP | Tools depend on stores, not on themselves over the wire. Compose via pipelines. |
| Tool caches results across calls | Caching belongs in the stores, not the tools. |
| Tool does long-running work (> 30s) | Return a `task_id`; add a `get_task_status` tool. (Out of scope for Phase 4.) |
| Tool skips schema validation ("it's a simple one") | Every tool validates. Simplicity is not a reason. |
| Tool uses `print()` instead of structured logging | Use the framework's logger. |

---

*End of skill.*
