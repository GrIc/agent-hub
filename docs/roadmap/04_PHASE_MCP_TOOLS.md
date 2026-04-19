# Phase 4 — MCP Server Refactor + Code Intelligence Tools

> **Mode**: `mcp-engineer` (see `.roomodes`).
> **Effort**: 4 weeks.
> **Prerequisite**: Phase 1 (grounding) + Phase 2 (graph) + Phase 3 (temporal) all complete OR at least Phase 1 if you sequence tools by category.
> **The product surface**. Everything before was foundational. This is what users see.

---

## 1. Objectives

1. Refactor the MCP server into a maintainable framework: one tool = one file with schema + handler + golden test.
2. Enforce the **citation contract**: every tool response that references code includes verifiable sources.
3. Ship 23 production-grade MCP tools across 7 categories (Phase 5 adds the remaining 6).
4. Provide SSE + stdio transports.
5. Provide auth + per-tool rate limits.

---

## 2. Phase 4 deliverables (overview)

| ID | Deliverable |
|----|-------------|
| `src/mcp/base.py` | `BaseTool` ABC, schema validator, error envelope |
| `src/mcp/server.py` | New entry point (replaces `src/mcp_server.py`) |
| `src/mcp/transports/sse.py` | SSE transport |
| `src/mcp/transports/stdio.py` | stdio transport |
| `src/mcp/middleware/auth.py` | Bearer token auth |
| `src/mcp/middleware/rate_limit.py` | Per-tool rate limiting |
| `src/mcp/middleware/citation.py` | Citation contract enforcement |
| `src/mcp/middleware/logging.py` | Structured JSON logs |
| `src/mcp/tools/*.py` | 23 tool implementations |
| `tests/golden/test_mcp_tools.py` | One golden test per tool |
| `docs/mcp/tools.md` | Auto-generated reference (built from tool schemas) |

---

## 3. Tasks — Framework first

### T-401 — Audit current `src/mcp_server.py`

**Mode**: `mcp-engineer`
**Effort**: 0.5 day

**CONTEXT**: Same pattern as T-301. Before rewriting, document.

**DELIVERABLE**: `docs/diagnostics/mcp_audit.md` listing each existing tool, its current schema, observed failure modes, latency.

---

### T-402 — Create `src/mcp/base.py` (BaseTool framework)

**Mode**: `mcp-engineer`
**Effort**: 2 days
**Depends on**: T-401.

**CONTEXT**
Every tool will inherit from `BaseTool`. The base class enforces the contract: schema validation, citation requirement, error envelope, structured logging.

**FILE**: `src/mcp/base.py`

```python
"""Base classes and middleware for the Agent Hub MCP server.

Every tool implements:
  class MyTool(BaseTool):
      name = "my_tool"
      description = "..."
      input_schema = { ... JSON Schema ... }
      output_schema = { ... JSON Schema ... }
      examples = [ {"input": {...}, "output": {...}}, ... ]
      requires_citations = True | False
      auth_required = True | False
      rate_limit_per_minute = 60

      def handle(self, args: dict) -> dict:
          ...

The framework handles:
  - input validation (jsonschema)
  - output validation
  - citation enforcement (if requires_citations)
  - error envelope normalization
  - rate limiting
  - structured logging
  - auth check
"""

from abc import ABC, abstractmethod
import jsonschema, time, json, logging, uuid

logger = logging.getLogger("mcp")

class ToolError(Exception):
    def __init__(self, code: str, message: str, hint: str = ""):
        self.code = code; self.message = message; self.hint = hint

class BaseTool(ABC):
    name: str
    description: str
    input_schema: dict
    output_schema: dict
    examples: list[dict] = []
    requires_citations: bool = False
    auth_required: bool = False
    rate_limit_per_minute: int = 60

    @abstractmethod
    def handle(self, args: dict) -> dict: ...

    def __call__(self, args: dict, *, context: dict) -> dict:
        call_id = str(uuid.uuid4())[:8]
        t0 = time.time()
        try:
            jsonschema.validate(args, self.input_schema)
        except jsonschema.ValidationError as e:
            return self._error("invalid_input", str(e), call_id, t0)

        try:
            result = self.handle(args)
        except ToolError as e:
            return self._error(e.code, e.message, call_id, t0, hint=e.hint)
        except Exception as e:
            logger.exception("tool=%s call=%s unhandled", self.name, call_id)
            return self._error("internal_error", str(e), call_id, t0)

        try:
            jsonschema.validate(result, self.output_schema)
        except jsonschema.ValidationError as e:
            logger.error("tool=%s call=%s invalid output: %s", self.name, call_id, e)
            return self._error("invalid_output", str(e), call_id, t0)

        if self.requires_citations:
            from src.mcp.middleware.citation import enforce_citations
            err = enforce_citations(result)
            if err:
                return self._error("citation_failure", err, call_id, t0)

        dur_ms = int((time.time() - t0) * 1000)
        logger.info(
            json.dumps({"tool": self.name, "call_id": call_id,
                        "duration_ms": dur_ms, "success": True})
        )
        return result

    def _error(self, code, message, call_id, t0, hint=""):
        dur_ms = int((time.time() - t0) * 1000)
        logger.warning(json.dumps({
            "tool": self.name, "call_id": call_id, "duration_ms": dur_ms,
            "success": False, "error_code": code,
        }))
        return {"error": {"code": code, "message": message, "hint": hint}}
```

**ACCEPTANCE**
- A trivial subclass `class EchoTool(BaseTool)` with name `echo` works end-to-end.
- Invalid input returns `{"error": {"code": "invalid_input", ...}}`.
- Logs are valid JSON on every call.

---

### T-403 — Citation enforcement middleware

**Mode**: `mcp-engineer` + `kip-engineer`
**Effort**: 1.5 days
**Depends on**: T-402, Phase 1 (`src/rag/identifiers.py` + grounding).

**CONTEXT**
The most important middleware. Every tool that returns code-related information includes a `sources: [{path, line_start, line_end}]` field. We verify each source exists and is reachable.

**FILE**: `src/mcp/middleware/citation.py`

```python
"""Citation contract enforcement.

Rules for any output containing 'sources':
  - sources is a list of {path, line_start, line_end}.
  - Each path MUST resolve to a file in the workspace.
  - line_start <= line_end <= file_line_count.
  - line_end - line_start <= 200 (no huge "everywhere" citations).

Additionally, if the output contains an 'identifiers_mentioned' list
(or extractable from the prose), each identifier MUST be findable in
at least one of the cited source ranges. Otherwise: citation_failure.
"""

from pathlib import Path
from src.rag.identifiers import extract_identifiers, detect_language

WORKSPACE = Path("workspace")  # configurable

def enforce_citations(result: dict) -> str | None:
    """Return None if OK, else an error message string."""
    sources = result.get("sources")
    if sources is None:
        return None  # tool didn't claim to cite — caller decides if that's OK
    if not isinstance(sources, list) or not sources:
        return "sources field present but empty"
    for src in sources:
        path = WORKSPACE / src["path"]
        if not path.exists():
            return f"cited path does not exist: {src['path']}"
        n_lines = sum(1 for _ in path.open(encoding='utf-8', errors='replace'))
        if not (1 <= src["line_start"] <= src["line_end"] <= n_lines):
            return f"line range {src['line_start']}-{src['line_end']} invalid for {src['path']} ({n_lines} lines)"
        if src["line_end"] - src["line_start"] > 200:
            return f"citation range too large: {src['path']}:{src['line_start']}-{src['line_end']}"

    # cross-check identifiers if present
    mentioned = result.get("identifiers_mentioned", [])
    if mentioned:
        cited_text = _read_cited_ranges(sources)
        cited_ids = extract_identifiers(cited_text, language=None)  # mixed
        for ident in mentioned:
            if ident not in cited_text:  # plain substring is fine for safety
                return f"identifier '{ident}' mentioned but not in cited ranges"
    return None


def _read_cited_ranges(sources: list[dict]) -> str:
    parts = []
    for src in sources:
        path = WORKSPACE / src["path"]
        with path.open(encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        parts.append("".join(lines[src["line_start"]-1:src["line_end"]]))
    return "\n".join(parts)
```

**ACCEPTANCE**
- A tool returning a fabricated `path: "fake.java"` is rejected with `citation_failure`.
- A tool returning a real path with an invalid range is rejected.
- A tool returning a valid range that doesn't contain a claimed identifier is rejected.
- A tool with no `sources` field is allowed (caller's responsibility).

**ANTI-PATTERNS**
- Do NOT skip the existence check on paths.
- Do NOT trust identifier matching alone — file existence is the hard guarantee.

---

### T-404 — Auth + rate limit middleware

**Mode**: `mcp-engineer`
**Effort**: 1 day
**Depends on**: T-402.

**CONTEXT**
Auth: optional bearer token, configured in `.env`. When enabled, all admin tools require auth; user-facing tools have it as opt-in via `auth_required = True`.
Rate limit: per-tool, in-memory token bucket. Override per IP or per token if auth on.

**FILES**: `src/mcp/middleware/auth.py`, `src/mcp/middleware/rate_limit.py`.

Both implemented as small functions called from the transport layer before invoking the tool.

**Config** (`config.yaml`):
```yaml
mcp:
  auth:
    enabled: false
    token_env: MCP_BEARER_TOKEN
  rate_limit:
    default_per_minute: 60
    per_tool:
      get_architecture_blueprint: 10  # expensive
      run_pipeline: 10
```

**ACCEPTANCE**
- With auth enabled, missing/wrong token → 401-equivalent in MCP error envelope.
- Exceeding rate limit → `{"error": {"code": "rate_limited", ...}}`.
- Admin tools always require auth when auth is enabled.

---

### T-405 — Transport: SSE + stdio

**Mode**: `mcp-engineer`
**Effort**: 1.5 days
**Depends on**: T-402..T-404.

**FILES**:
- `src/mcp/transports/sse.py`: integrate with the existing FastAPI app under `/mcp/sse`.
- `src/mcp/transports/stdio.py`: a `python -m src.mcp.server --stdio` entrypoint reading JSON-RPC messages from stdin.

Both use the same tool registry (loaded from `src/mcp/tools/*.py` via auto-discovery at startup).

**ACCEPTANCE**
- `python -m src.mcp.server --stdio < example_request.json` returns a valid response.
- `curl -N http://localhost:8080/mcp/sse` connects.
- Both transports list the same tools via `list_tools`.

---

### T-406 — Auto-discovery of tools

**Mode**: `mcp-engineer`
**Effort**: 0.5 day

**CONTEXT**: At server startup, scan `src/mcp/tools/` for any subclass of `BaseTool` and register it. This makes adding tools a one-file change.

**FILE**: `src/mcp/registry.py` with `discover_tools(package="src.mcp.tools") -> dict[str, BaseTool]`.

---

### T-407 — Auto-generated docs from tool schemas

**Mode**: `mcp-engineer`
**Effort**: 1 day

**CONTEXT**: Run a script `scripts/build_mcp_docs.py` that walks the registry and emits `docs/mcp/tools.md`: one section per tool, with description, input/output schemas (rendered as a table), examples.

**ACCEPTANCE**: After running, `docs/mcp/tools.md` is up to date and committed.

---

## 4. Tasks — Tools (Phase 4 catalog)

Each tool is one file under `src/mcp/tools/`. The framework handles validation, logging, citation enforcement. The agent's job per tool is small: implement `handle(args)`.

### Tool group A: Meta + admin (4 tools)

| Tool | Auth | Description |
|------|------|-------------|
| `list_tools` | No | Returns the tool catalog. |
| `reindex` | Yes | Trigger `/scan` + `synthesize` + `ingest`. |
| `ingest_files` | Yes | Index ad-hoc files. |
| `get_coverage_report` | Yes | Returns the quality report. |

**T-410..413**: one task each. ~0.5 day each.

---

### Tool group B: Retrieval (3 tools)

| Tool | Description |
|------|-------------|
| `find_code(intent, filters?)` | Semantic code search with intent + filters (block, module, doc_level, content_type, language). Returns ranked snippets with sources. |
| `find_similar(reference, kind)` | Given a file/class/description, return similar implementations. |
| `ask_expert(question, scope?)` | RAG-powered Q&A with **mandatory** citations. Output requires `sources` field. |

**T-420..422**: one task each. ~1.5 day each.

`ask_expert` is special: it goes through `_llm_call_grounded` (Phase 1) AND the citation middleware (T-403). Failure modes both at index time and serve time are blocked.

---

### Tool group C: Architecture (4 tools)

| Tool | Description |
|------|-------------|
| `get_architecture_blueprint(feature_description)` | **Flagship.** Returns structured plan: similar features, recommended modules, patterns, insertion points, tests, risks, sources. |
| `locate_feature(description)` | "Where in the codebase does X live?" Returns ranked file paths with confidence. |
| `guided_tour(topic)` | Markdown reading order for a module (3-5 anchor files + commentary). |
| `explain_module(module_id)` | Returns a 300-word summary from L1/L2 synthesis. |

**T-430..433**: one task each. `get_architecture_blueprint` is 3 days; others 1-1.5 days.

`get_architecture_blueprint` composes other tools internally:
1. `find_similar(feature_description, kind="auto")` → similar features.
2. For each similar feature: `get_callers` + `get_callees` → recommended modules.
3. `find_pattern_for(feature_description)` → patterns (Phase 5; for Phase 4, return empty list with a TODO note).
4. `preview_impact(insertion_points)` → risks.
5. Heavy-model LLM call to compose the final plan, GROUNDED against all the above + citation contract.

---

### Tool group D: Graph (6 tools)

All depend on Phase 2's graph store.

| Tool | Description |
|------|-------------|
| `get_callers(symbol, limit?)` | Who calls this? |
| `get_callees(symbol, depth?)` | What does this call? |
| `get_module_dependencies(module, direction)` | in/out/both. |
| `shortest_path(from_symbol, to_symbol)` | Path in the call graph. |
| `preview_impact(changed_files: [...])` | Impacted modules + tests with weighted scores. |
| `find_hub_modules(threshold?)` | Utility/hub modules to be careful with. |

**T-440..445**: one task each, ~0.5 day each (graph store does heavy lifting). Citations come from `node.file_path` + `line_start/line_end`.

---

### Tool group E: Temporal (5 tools)

All depend on Phase 3's temporal store.

| Tool | Description |
|------|-------------|
| `recent_changes(scope?, since?)` | Enriched commit list, filterable. |
| `explain_change(commit_sha)` | Narrative summary + impacted modules + risk. |
| `why_does_this_exist(symbol)` | Walks back to the introducing commit. |
| `what_changed_here(file, since?)` | Per-file timeline. |
| `blame_plus(file, line)` | Git blame + enriched commit summary. |

**T-450..454**: ~0.5 day each (temporal store does the work).

---

### Tool group F: Conventions (1 tool, others in Phase 5)

| Tool | Description |
|------|-------------|
| `check_conventions(file_content, language?)` | Lint proposed code against inferred rules. **Phase 5 builds the rules**; in Phase 4 this returns a stub `{rules_loaded: 0, message: "not yet trained"}`. |

**T-460**: 0.5 day stub. Real implementation in Phase 5.

---

## 5. Per-tool task template

Every tool task follows this template. Example for `find_code`:

```
TASK: T-420 — Implement MCP tool find_code

CONTEXT
Semantic code search via the existing RAG store, with filters.
Returns ranked results with mandatory source citations.

FILES
Create: src/mcp/tools/find_code.py

CHANGES
- Inherit from BaseTool.
- name = "find_code"
- input_schema:
    intent: string, required, max 500 chars
    filters: object (optional)
      module: string
      block: string
      doc_level: string enum [L0, L1, L2, L3, code]
      content_type: string enum [code, codex_doc, synthesis, config, test]
      language: string
    top_k: integer, default 8, max 20
- output_schema:
    results: list of objects
      snippet: string (first 1000 chars of chunk)
      score: number
      source: { path, line_start, line_end }
    notes: string (optional, e.g. "0 results matched filters")
    sources: list of { path, line_start, line_end }    # MANDATORY for citation contract
- requires_citations = True
- handle(args):
    1. build where_clause from filters
    2. call store.search(query=args["intent"], top_k=args["top_k"], where=where_clause)
    3. for each result: project to output schema
    4. populate sources from each result's metadata
    5. if no results: return {"results": [], "notes": "...", "sources": []}
       (citation enforcement allows empty sources when explicitly tagged via notes)

ACCEPTANCE
- Golden test: query "authentication" on the fixture returns ≥1 result with valid source.
- Filter test: filter doc_level=L0 returns only L0 chunks.
- Citation test: every returned source has a real path + valid line range.
- Latency P95 <800ms on the user's workspace.

ANTI-PATTERNS
- Do NOT raise on empty results — return empty list.
- Do NOT include the breadcrumb prefix in the snippet (it's an indexing artifact).
- Do NOT exceed top_k=20.
```

Replicate this template for every tool. Tasks T-410 through T-460 are decomposed in `docs/roadmap/tasks/T-4XX-*.md` (generated by the agent — one file per task, brief, follows the template above).

---

## 6. Phase 4 success gate

- [ ] `list_tools` MCP call returns 23 tools (Phase 4 set).
- [ ] Every tool has a passing golden test in CI.
- [ ] Every tool that returns code-related info passes the citation contract.
- [ ] `docs/mcp/tools.md` is auto-generated and committed.
- [ ] On the user's workspace: `get_architecture_blueprint("add caching to KPI cloud view solver")` returns a structurally valid result with ≥3 similar features, ≥2 recommended modules, ≥1 insertion point, all verifiable.
- [ ] Hallucinated paths in tool responses (over a 100-call sample): 0.
- [ ] Roo Code can connect to `/mcp/sse` and successfully invoke 5 different tools.
- [ ] Claude Code can connect via stdio and successfully invoke 5 different tools.

---

## 7. Files Phase 4 produces / modifies

| File | New / Modified |
|------|----------------|
| `src/mcp/base.py` | NEW |
| `src/mcp/registry.py` | NEW |
| `src/mcp/server.py` | NEW (replaces `src/mcp_server.py`) |
| `src/mcp_server.py` | DELETED |
| `src/mcp/transports/sse.py` | NEW |
| `src/mcp/transports/stdio.py` | NEW |
| `src/mcp/middleware/auth.py` | NEW |
| `src/mcp/middleware/rate_limit.py` | NEW |
| `src/mcp/middleware/citation.py` | NEW |
| `src/mcp/middleware/logging.py` | NEW |
| `src/mcp/tools/*.py` | NEW (23 files) |
| `tests/golden/test_mcp_tools.py` | NEW |
| `scripts/build_mcp_docs.py` | NEW |
| `docs/mcp/tools.md` | NEW (auto-generated, committed) |
| `docs/diagnostics/mcp_audit.md` | NEW (T-401) |
| `config.yaml` | MODIFIED (mcp section) |

---

*End of Phase 4. With grounded indexing (Phase 1), structural graph (Phase 2), enriched commits (Phase 3), and validated MCP tools (Phase 4), Agent Hub now delivers on the MCP-first thesis.*
