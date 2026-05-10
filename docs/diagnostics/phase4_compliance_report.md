# Phase 4 Compliance Report — MCP Server Refactor + Code Intelligence Tools

**Date**: 2026-05-10  
**Specification**: [`docs/roadmap/04_PHASE_MCP_TOOLS.md`](docs/roadmap/04_PHASE_MCP_TOOLS.md)  
**Scope**: Framework layer + middleware + transports + tool implementations  
**Status**: ⚠️ **PARTIAL** — Framework layer implemented; core deliverables missing

---

## 1. File Existence Matrix

| # | Spec File | Status | Notes |
|---|-----------|--------|-------|
| 1 | `src/mcp/base.py` | ✅ | Exists |
| 2 | `src/mcp/server.py` | ❌ | **MISSING** — Required as new entry point (T-405) |
| 3 | `src/mcp/transports/sse.py` | ✅ | Exists |
| 4 | `src/mcp/transports/stdio.py` | ✅ | Exists |
| 5 | `src/mcp/middleware/auth.py` | ✅ | Exists |
| 6 | `src/mcp/middleware/rate_limit.py` | ✅ | Exists |
| 7 | `src/mcp/middleware/citation.py` | ✅ | Exists |
| 8 | `src/mcp/middleware/logging.py` | ❌ | **MISSING** — Required for structured JSON logs (T-404) |
| 9 | `src/mcp/tools/*.py` (23 files) | ❌ | **MISSING** — Only empty `__init__.py` exists |
| 10 | `tests/golden/test_mcp_tools.py` | ❌ | **MISSING** — Golden tests for all tools |
| 11 | `scripts/build_mcp_docs.py` | ✅ | Exists |
| 12 | `docs/mcp/tools.md` | ✅ | Exists (but likely stale — no tools to document) |
| 13 | `docs/diagnostics/mcp_audit.md` | ✅ | Exists (T-401 deliverable) |
| 14 | `src/mcp_server.py` | ⚠️ | **STILL EXISTS** — Spec says DELETED |
| 15 | `config.yaml` (mcp section) | ⚠️ | Not verified in this review |

---

## 2. Per-File Compliance Analysis

### 2.1 [`src/mcp/base.py`](src/mcp/base.py) — T-402 — ⚠️ Minor Deviations

**Compliant elements:**
- ✅ `ToolError` exception class with `code`, `message`, `hint` attributes (line 33-37)
- ✅ `BaseTool` ABC with all required class attributes: `name`, `description`, `input_schema`, `output_schema`, `examples`, `requires_citations`, `auth_required`, `rate_limit_per_minute` (line 40-48)
- ✅ Abstract `handle(self, args: dict) -> dict` method (line 50-52)
- ✅ `__call__(self, args: dict, *, context: dict) -> dict` with full pipeline:
  - ✅ Input validation via `jsonschema.validate()` (line 57-60)
  - ✅ Handle call with `ToolError` and generic exception handling (line 62-68)
  - ✅ Output validation via `jsonschema.validate()` (line 70-74)
  - ✅ Citation enforcement via `enforce_citations()` (line 76-80)
  - ✅ Structured JSON logging on success (line 82-86)
- ✅ `_error()` method returning normalized error envelope `{"error": {"code", "message", "hint"}}` (line 89-95)
- ✅ Structured JSON logging on error (line 91-94)
- ✅ Call ID generation via `uuid.uuid4()[:8]` (line 55)
- ✅ Duration tracking in milliseconds (line 82, 90)

**Deviations:**
| # | Spec Requirement | Implementation | Severity |
|---|-----------------|----------------|----------|
| 1 | Spec shows `import jsonschema, time, json, logging, uuid` on one line | Implementation uses same imports (no functional difference) | Trivial |
| 2 | Spec docstring mentions "rate limiting" and "auth check" in framework handling list | Implementation does NOT enforce rate limiting or auth in `__call__()` — these are left to transport layer | ⚠️ Minor |
| 3 | Spec shows `from src.mcp.middleware.citation import enforce_citations` as lazy import inside `__call__` | Implementation matches this pattern (line 77) | ✅ |

**Assessment**: The core framework is well-implemented and matches the spec. The docstring claims rate limiting and auth are handled by the framework, but these are actually enforced by middleware functions called from the transport layer. This is a documentation inconsistency, not a functional gap.

---

### 2.2 [`src/mcp/middleware/citation.py`](src/mcp/middleware/citation.py) — T-403 — ✅ Fully Compliant

**Compliant elements:**
- ✅ `enforce_citations(result: dict) -> str | None` function signature (line 19)
- ✅ Returns `None` when no `sources` field present (line 23-24)
- ✅ Returns error for empty `sources` list (line 25-26)
- ✅ Validates each source entry has required keys: `path`, `line_start`, `line_end` (line 29)
- ✅ Checks path existence via `WORKSPACE / src["path"]` (line 31-33)
- ✅ Counts file lines and validates `1 <= line_start <= line_end <= n_lines` (line 36-40)
- ✅ Enforces citation range <= 200 lines (line 41-42)
- ✅ Cross-checks `identifiers_mentioned` against cited text (line 45-53)
- ✅ `_read_cited_ranges()` helper function with correct 1-based to 0-based conversion (line 57-69)
- ✅ Configurable workspace via `WORKSPACE` variable (line 16)
- ✅ Proper docstring matching spec intent (lines 1-10)

**Additional improvements over spec:**
- ✅ Added try/except around file reading (line 35-38) — spec does not handle read errors
- ✅ Added explicit key validation for source entry format (line 29) — spec assumes well-formed entries

**Assessment**: Fully compliant with spec. Implementation is actually more robust than the spec example.

---

### 2.3 [`src/mcp/middleware/auth.py`](src/mcp/middleware/auth.py) — T-404 — ✅ Fully Compliant

**Compliant elements:**
- ✅ `enforce_auth(context: dict) -> str | None` function (line 29)
- ✅ Reads config from `config.yaml` under `mcp.auth` (line 37-39)
- ✅ Supports `token_env` configuration (line 45)
- ✅ Case-insensitive `Authorization` header lookup (line 54-59)
- ✅ Bearer token format validation: `"Bearer <token>"` (line 64-66)
- ✅ Token comparison (line 68)
- ✅ No-op when auth disabled (line 40-42)
- ✅ Stores `auth_token` in context for downstream middleware (line 73)
- ✅ Config caching to avoid repeated I/O (line 20-26)

**Additional improvements over spec:**
- ✅ Returns descriptive error strings for each failure mode (missing header, invalid format, wrong token, not configured)
- ✅ Uses `src.config.load_config()` for configuration loading

**Assessment**: Fully compliant with spec. Well-structured with proper error messages.

---

### 2.4 [`src/mcp/middleware/rate_limit.py`](src/mcp/middleware/rate_limit.py) — T-404 — ✅ Fully Compliant

**Compliant elements:**
- ✅ `enforce_rate_limit(context: dict, tool_name: str) -> str | None` function (line 33)
- ✅ Reads config from `config.yaml` under `mcp.rate_limit` (line 41-43)
- ✅ Supports `default_per_minute` (line 48)
- ✅ Supports `per_tool` overrides (line 49-50)
- ✅ In-memory token bucket implementation (line 20, 52-62)
- ✅ 60-second sliding window (line 55)
- ✅ Returns descriptive error string when limit exceeded (line 60)
- ✅ No-op when no rate limit config (line 44-46)
- ✅ Config caching (line 23-29)

**Additional improvements over spec:**
- ✅ Handles missing config gracefully (treats as unlimited)

**Assessment**: Fully compliant with spec. The token bucket is simple but effective for the stated requirements.

---

### 2.5 [`src/mcp/transports/sse.py`](src/mcp/transports/sse.py) — T-405 — ⚠️ Minor Deviations

**Compliant elements:**
- ✅ `create_sse_app()` function returning ASGI app (line 85)
- ✅ SSE endpoint for connection establishment (line 150-156)
- ✅ POST message endpoint (line 158-164)
- ✅ Configurable host, port, endpoint, sse_path via env vars and config (line 54-82)
- ✅ CORS middleware support (line 180-191)
- ✅ App caching for idempotency (line 51, 121-125)
- ✅ `run_sse_server()` for direct execution (line 200)
- ✅ `__main__` block for `python -m src.mcp.transports.sse` (line 240-245)

**Deviations:**
| # | Spec Requirement | Implementation | Severity |
|---|-----------------|----------------|----------|
| 1 | Spec says "integrate with the existing FastAPI app under `/mcp/sse`" | Implementation creates its own Starlette app rather than integrating with an existing FastAPI app | ⚠️ Minor |
| 2 | Spec mentions `SseServerTransport` from `mcp.server.sse` | Implementation imports from `mcp.server.sse` (line 131) — assumes MCP SDK is installed | ⚠️ Minor |
| 3 | Spec does not mention CORS configuration | Implementation adds CORS middleware support (line 180-191) | ✅ Positive |

**Assessment**: The implementation is functionally correct but creates a standalone app rather than integrating with an existing FastAPI app. This is a reasonable architectural choice but deviates from the spec wording.

---

### 2.6 [`src/mcp/transports/stdio.py`](src/mcp/transports/stdio.py) — T-405 — ⚠️ Minor Deviations

**Compliant elements:**
- ✅ `create_server()` function returning MCP server instance (line 45)
- ✅ `run_stdio_server()` function (line 106)
- ✅ CLI argument parser with `--stdio` flag (line 151-176)
- ✅ JSON-RPC message handling via stdio (line 145-147)
- ✅ Configurable log level (line 128-131)
- ✅ Server caching for idempotency (line 42, 73-77)

**Deviations:**
| # | Spec Requirement | Implementation | Severity |
|---|-----------------|----------------|----------|
| 1 | Spec says entry point is `python -m src.mcp.server --stdio` | Implementation is at `src/mcp/transports/stdio.py`, not `src/mcp/server.py` | ⚠️ Minor (depends on server.py existence) |
| 2 | Spec says "reading JSON-RPC messages from stdin" | Implementation uses `server.run(transport="stdio")` which handles this internally via MCP SDK | ✅ Acceptable |

**Assessment**: The stdio transport is well-implemented. The main concern is that the spec entry point (`src/mcp/server.py`) does not exist, so the stdio transport cannot be invoked as specified.

---

### 2.7 [`src/mcp/registry.py`](src/mcp/registry.py) — T-406 — ✅ Fully Compliant

**Compliant elements:**
- ✅ `discover_tools(package: str = "src.mcp.tools") -> Dict[str, BaseTool]` function (line 25)
- ✅ Auto-discovery via `pkgutil.iter_modules()` (line 98)
- ✅ Imports each module and inspects for `BaseTool` subclasses (line 107, 143)
- ✅ Skips sub-packages (line 100-102)
- ✅ Skips abstract classes (line 225)
- ✅ Skips classes not defined in the scanned module (line 150-151)
- ✅ Handles import errors gracefully (line 108-114)
- ✅ Handles instantiation errors (line 158-176)
- ✅ Validates `name` attribute (line 179-187)
- ✅ Handles duplicate names (line 189-196)
- ✅ Comprehensive docstrings with examples (lines 26-64)

**Assessment**: Fully compliant with spec. Implementation is robust with extensive error handling and logging.

---

### 2.8 [`scripts/build_mcp_docs.py`](scripts/build_mcp_docs.py) — T-407 — ✅ Fully Compliant

**Compliant elements:**
- ✅ Scans registry via `discover_tools()` (line 216)
- ✅ Emits Markdown to `docs/mcp/tools.md` (line 34)
- ✅ One section per tool with description, input/output schemas, examples (line 67-130)
- ✅ Extra attributes rendering: `requires_citations`, `auth_required`, `rate_limit_per_minute` (line 38-42, 120-128)
- ✅ Creates output directory if needed (line 173-180)
- ✅ Handles empty tool registry gracefully (line 158-163)
- ✅ CLI entry point via `__main__` block (line 234-235)

**Assessment**: Fully compliant with spec. Well-structured and handles edge cases.

---

### 2.9 [`docs/diagnostics/mcp_audit.md`](docs/diagnostics/mcp_audit.md) — T-401 — ✅ Fully Compliant

**Compliant elements:**
- ✅ Lists each existing tool with schema, failure modes, latency
- ✅ Overall observations section (9 categories)
- ✅ Risk summary table
- ✅ Recommendations for T-402 through T-407

**Assessment**: Fully compliant with T-401 deliverable. Comprehensive audit report.

---

## 3. Missing Deliverables

### 3.1 Critical Gaps (❌)

| ID | File | Spec Reference | Impact |
|----|------|----------------|--------|
| M1 | `src/mcp/server.py` | T-405, Section 2 | **BLOCKING** — No server entry point. Spec says this replaces `src/mcp_server.py`. Without it, neither SSE nor stdio transports can be invoked as specified. |
| M2 | `src/mcp/middleware/logging.py` | T-404, Section 2 | **HIGH** — Structured JSON logging middleware is required by spec but not implemented. The `base.py` uses `logger.info()` and `logger.warning()` directly, but there is no middleware to format these as structured JSON. |
| M3 | `src/mcp/tools/*.py` (23 tool files) | Section 4, Tasks T-410..T-460 | **BLOCKING** — Zero tool implementations exist. The spec requires 23 tools across 7 categories. Only an empty `__init__.py` exists. |
| M4 | `tests/golden/test_mcp_tools.py` | Section 2, Section 6 | **HIGH** — Golden tests are required for every tool per the Phase 4 success gate. |

### 3.2 Minor Gaps (⚠️)

| ID | File | Spec Reference | Impact |
|----|------|----------------|--------|
| m1 | `src/mcp_server.py` (should be deleted) | Section 7 | **LOW** — Old entry point still exists. Spec says it should be DELETED. |
| m2 | `config.yaml` (mcp section) | Section 2 (T-404) | **MEDIUM** — Spec requires `mcp.auth` and `mcp.rate_limit` config sections. Not verified in this review. |
| m3 | `docs/mcp/tools.md` | T-407 | **LOW** — File exists but is likely stale since no tools are registered. Will be regenerated once tools are implemented. |

---

## 4. Specification vs Implementation Gap Analysis

### 4.1 Tool Implementation Status (Section 4 of Spec)

| Category | Required Tools | Implemented | Status |
|----------|---------------|-------------|--------|
| A: Meta + admin | `list_tools`, `reindex`, `ingest_files`, `get_coverage_report` (4) | 0 | ❌ |
| B: Retrieval | `find_code`, `find_similar`, `ask_expert` (3) | 0 | ❌ |
| C: Architecture | `get_architecture_blueprint`, `locate_feature`, `guided_tour`, `explain_module` (4) | 0 | ❌ |
| D: Graph | `get_callers`, `get_callees`, `get_module_dependencies`, `shortest_path`, `preview_impact`, `find_hub_modules` (6) | 0 | ❌ |
| E: Temporal | `recent_changes`, `explain_change`, `why_does_this_exist`, `what_changed_here`, `blame_plus` (5) | 0 | ❌ |
| F: Conventions | `check_conventions` (1, stub) | 0 | ❌ |
| **Total** | **23** | **0** | **❌** |

### 4.2 Phase 4 Success Gate Compliance

| Gate | Status | Notes |
|------|--------|-------|
| `list_tools` returns 23 tools | ❌ | No tools registered |
| Every tool has passing golden test | ❌ | No tests exist |
| Every code-related tool passes citation contract | ⚠️ | Citation middleware exists but no tools to test |
| `docs/mcp/tools.md` auto-generated and committed | ⚠️ | File exists but likely stale |
| `get_architecture_blueprint` returns valid result | ❌ | Tool not implemented |
| 0 hallucinated paths | ⚠️ | Cannot evaluate — no tools |
| Roo Code can invoke 5 tools via SSE | ❌ | No tools, no server entry point |
| Claude Code can invoke 5 tools via stdio | ❌ | No tools, no server entry point |

---

## 5. Code Quality Assessment

### 5.1 Strengths
- **Docstrings**: All implemented files have comprehensive docstrings with parameter descriptions, return types, and examples.
- **Type hints**: Consistent use of type hints throughout (e.g., `Dict[str, BaseTool]`, `str | None`).
- **Error handling**: Robust try/except blocks with meaningful error messages and logging.
- **Configuration**: Lazy loading with caching pattern used consistently across middleware modules.
- **Logging**: Structured logging with `logging.getLogger("mcp.*")` namespace hierarchy.
- **Modularity**: Clean separation of concerns — base framework, middleware, transports, and registry are well-isolated.

### 5.2 Areas for Improvement
- **`base.py` imports**: Line 28 uses `import jsonschema, time, json, logging, uuid` — PEP 8 recommends one import per line for readability.
- **Config caching thread safety**: `_CONFIG_CACHE` in auth.py and rate_limit.py is not thread-safe. If the MCP server handles concurrent requests, race conditions could occur during first access.
- **Rate limit state**: `_RATE_LIMIT_STATE` in rate_limit.py is a plain dict — not thread-safe for concurrent access.
- **Citation middleware**: `WORKSPACE = Path("workspace")` is hardcoded — spec says "configurable" but no mechanism is provided to override it at runtime.
- **No `__init__.py` exports**: The `src/mcp/` package does not export `BaseTool`, `ToolError`, or `discover_tools` from its `__init__.py`, forcing consumers to use full import paths.

---

## 6. Overall Assessment

### Phase 4 Readiness: ⚠️ **NOT READY** — Framework Layer Complete, Core Functionality Missing

**Completed (Framework Layer — ~30% of Phase 4):**
- ✅ `BaseTool` ABC with schema validation, error envelope, citation enforcement hook
- ✅ Citation middleware (`enforce_citations`)
- ✅ Auth middleware (`enforce_auth`)
- ✅ Rate limit middleware (`enforce_rate_limit`)
- ✅ SSE transport (`create_sse_app`)
- ✅ stdio transport (`create_server`, `run_stdio_server`)
- ✅ Tool registry (`discover_tools`)
- ✅ Documentation generator (`build_mcp_docs.py`)
- ✅ Audit report (`mcp_audit.md`)

**Missing (Core Functionality — ~70% of Phase 4):**
- ❌ Server entry point (`src/mcp/server.py`)
- ❌ Logging middleware (`src/mcp/middleware/logging.py`)
- ❌ All 23 tool implementations
- ❌ Golden tests (`tests/golden/test_mcp_tools.py`)
- ⚠️ Old `src/mcp_server.py` not deleted

### Recommendation

The framework layer is **well-implemented** and serves as a solid foundation. However, Phase 4 cannot be considered complete until:

1. **`src/mcp/server.py`** is created as the unified server entry point that wires together the registry, transports, and middleware.
2. **`src/mcp/middleware/logging.py`** is implemented for structured JSON logging.
3. **All 23 tool implementations** are created under `src/mcp/tools/`.
4. **Golden tests** are written and passing for each tool.
5. **`src/mcp_server.py`** is deleted to avoid confusion.

The framework code itself is production-quality and ready for tool implementations to be built on top of it.

---

*Report generated: 2026-05-10*
