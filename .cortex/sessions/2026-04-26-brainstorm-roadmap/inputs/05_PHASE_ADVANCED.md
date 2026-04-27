# Phase 5 — Advanced Features (Pipelines, Wiki, Multi-repo, Telemetry)

> **Mode**: `roadmap-executor`, `mcp-engineer` (for tool additions).
> **Effort**: 4 weeks.
> **Prerequisite**: Phases 1-4 complete.

---

## 1. Scope

Four mostly-independent workstreams, executable in parallel:

| # | Workstream | Decision | Effort |
|---|-----------|----------|--------|
| A | Custom YAML pipelines + 3 MCP tools | (orig) | 1.5 weeks |
| B | Living auto-generated wiki + 2 MCP tools | (orig) | 1 week |
| C | Pattern & convention discovery + 4 MCP tools | (orig) | 1.5 weeks |
| D | Multi-repo federation | DECIDE-6 | 1.5 weeks |
| E | Opt-in telemetry | DECIDE-7 | 0.5 week |

Parallelization: A / B / C / D independent. E can ship anytime.

---

## 2. Workstream A — Custom YAML Pipelines

### Context
Power users define workflows declaratively: "onboard-feature = blueprint → find_similar → preview_impact". No forking. No Python. Composes existing MCP tools.

### T-501 — Pipeline engine `src/pipelines/`

**Effort**: 3 days
**Files**: `src/pipelines/loader.py`, `src/pipelines/runner.py`, `src/pipelines/context.py`

Loader reads `pipelines/*.yaml`. Schema:

```yaml
# pipelines/onboard-feature.yaml
name: onboard-feature
description: "Full onboarding plan for a new feature"
inputs:
  feature_description: { type: string, required: true }
steps:
  - id: blueprint
    tool: get_architecture_blueprint
    args:
      feature_description: "{{ inputs.feature_description }}"
  - id: similar
    tool: find_similar
    args:
      reference: "{{ inputs.feature_description }}"
      kind: description
  - id: impacts
    tool: preview_impact
    args:
      changed_files: "{{ blueprint.recommended_files }}"
output:
  plan: "{{ blueprint }}"
  similar: "{{ similar }}"
  risk: "{{ impacts }}"
```

Runner: topological sort by id references, execute each step via the MCP registry, interpolate `{{ ... }}` via a safe minijinja-like sandbox (no arbitrary code exec).

**Acceptance**:
- 3 built-in pipelines ship: `onboard-feature`, `review-patch`, `explain-module`.
- `python -m src.pipelines.run onboard-feature --feature_description="..."` works from CLI.
- Cycles / missing references raise clear errors before execution.

**Anti-patterns**:
- Do NOT use raw `eval()` or a full Python template engine. Whitelist `{{ id.path.to.value }}` only.
- Do NOT let pipelines invoke shell commands — MCP tools only.

### T-502 — 3 MCP tools: `list_pipelines`, `explain_pipeline`, `run_pipeline`

**Effort**: 1.5 days

`run_pipeline` is a heavyweight tool (auth + lower rate limit). It returns the aggregated output of all steps PLUS individual step outputs for debugging.

**Acceptance**: each pipeline is runnable through MCP from Roo Code.

### T-503 — 2 more built-in pipelines

**Effort**: 1 day

- `daily-changelog` — runs temporal digest + delivers.
- `wiki-refresh` — regenerates wiki (depends on workstream B).

---

## 3. Workstream B — Living auto-generated Wiki

### Context
One markdown page per module + an index. Regenerated from the existing index (no new LLM work — just formatting). Mermaid diagrams auto-rendered from graph edges.

### T-510 — Wiki renderer `scripts/build_wiki.py`

**Effort**: 3 days

Walks the synthesis docs + graph store + enriched commits, emits `wiki/` directory:

```
wiki/
├── index.md                # all modules, searchable
├── modules/
│   ├── MODULE_X.md         # description (L1), callers, callees, recent changes, tests
│   └── ...
├── services.md             # all Service nodes
├── conventions.md          # from workstream C
└── diagrams/
    └── dependencies.mmd    # Mermaid graph
```

**Acceptance**: wiki rebuild <2 min on user's workspace; each module page cites its source files.

### T-511 — `/wiki` web route

**Effort**: 1 day

Serve `wiki/` as static markdown rendered via `markdown` + a minimal template.

### T-512 — 2 MCP tools: `get_wiki_page(module)`, `wiki_search(query)`

**Effort**: 1 day

Pure reads from the generated wiki directory. Cheap.

---

## 4. Workstream C — Pattern & convention discovery

### Context
Extract implicit patterns: dependency injection style, repository pattern, error handling, logging. Use these to:
- Populate the wiki's conventions page.
- Power a real `check_conventions` MCP tool (replacing the Phase 4 stub).
- Add `list_patterns`, `get_pattern`, `find_pattern_for` tools.

### T-520 — Pattern extractor `scripts/extract_patterns.py`

**Effort**: 3 days

Heuristic + LLM hybrid:
1. Cluster similar classes by AST signature + name pattern (regex families: `*Repository`, `*Service`, `*Controller`, `*Handler`).
2. For each cluster (≥3 members): LLM call — describe the pattern (grounded against 3 sample files from cluster).
3. Save to `context/patterns/<pattern_id>.yaml`.

Output schema per pattern:
```yaml
id: repository-pattern
name: "Repository Pattern"
members: [ClassA, ClassB, ClassC, ...]
description: "..."
template_fingerprint:
  name_regex: ".*Repository$"
  required_methods: [findAll, findById, save, deleteById]
  required_annotations: [@Repository]
examples:
  - { file: "...", line: ... }
```

**Acceptance**: on user's workspace, ≥3 patterns extracted with correct members.

### T-521 — 4 MCP tools

**Effort**: 2 days

| Tool | Description |
|------|-------------|
| `list_patterns` | All discovered patterns. |
| `get_pattern(id)` | Detail view. |
| `find_pattern_for(description)` | Which pattern fits this feature? |
| `check_conventions(file_content, language?)` | Real implementation: check against applicable patterns. Returns list of issues with severity {info, warn, error} — NOT blocking. |

`check_conventions` returns advisory output: "this looks like a Repository but you're missing `deleteById`". Never returns `error` severity alone — always informational.

**Acceptance**: running `check_conventions` on a user file produces useful, grounded suggestions with references to example implementations.

---

## 5. Workstream D — Multi-repo federation (DECIDE-6)

### Context
Large orgs have multiple repos that reference each other. Agent Hub should be able to index N repos and answer cross-repo queries.

### T-530 — Config + indexer support

**Effort**: 4 days

Config extension:
```yaml
workspaces:
  - id: main-app
    path: /workspaces/main-app
    language: java
    is_primary: true
  - id: shared-libs
    path: /workspaces/shared-libs
    language: java
  - id: frontend
    path: /workspaces/frontend
    language: typescript
```

- All stores (ChromaDB, graph SQLite, temporal SQLite) gain a `workspace_id` column/field.
- Queries filter by workspace, or run across all (default: primary only).
- Ingest loop iterates per workspace.

### T-531 — `workspace` parameter on tools

**Effort**: 2 days

Every tool gains optional `workspace: str | "all" = "primary"`. Responses include `workspace_id` in source metadata.

### T-532 — Cross-repo `depends_on` edges

**Effort**: 2 days

When resolving imports (Phase 2, T-204), if an import's FQN matches a class in another workspace, create a cross-workspace edge `depends_on` with the target workspace_id.

**Acceptance**: `get_callees("SomeClass", workspace="all")` traverses cross-repo edges; tool responses annotate cross-repo citations clearly.

**Anti-patterns**: do NOT merge the three stores into one giant DB — keep them separate with a shared query layer.

---

## 6. Workstream E — Opt-in telemetry (DECIDE-7)

### Context
Per DECIDE-7 (!), telemetry is OPT-IN. The user was emphatic. Ship disabled by default; no surprise data exfiltration.

### T-540 — Anonymous usage metrics

**Effort**: 2 days

Config:
```yaml
telemetry:
  enabled: false                 # default OFF
  endpoint: ""                   # user sets if they want to collect
  anonymous: true                # never send workspace contents or paths
  events:
    - tool_invocation            # tool name, duration, success — NO args, NO results
    - pipeline_run
    - indexing_complete
```

Implementation:
- A simple background queue + HTTP POST batcher.
- Endpoint is self-hosted (user decides). No default endpoint pointing to Anthropic / anywhere.
- Every event payload documented in `docs/telemetry.md`.
- A `telemetry_consent_given` flag in config must also be explicitly `true`; if missing, warn on startup "telemetry.enabled=true but telemetry_consent_given=false, events discarded".

**Acceptance**: default install sends zero network traffic. Enabling requires two explicit opt-in flags.

**Anti-patterns**:
- Do NOT include file paths, workspace names, or code snippets in telemetry.
- Do NOT make it "just so much easier to enable by default".

---

## 7. Phase 5 success gate

- [ ] 3 pipelines built-in + `run_pipeline` works end-to-end via MCP.
- [ ] `/wiki` serves a generated page for every module in the graph.
- [ ] `list_patterns` returns ≥3 patterns on user's workspace; `check_conventions` gives grounded advice.
- [ ] Multi-repo: at least 2 workspaces simultaneously indexed, one tool call crosses repos correctly.
- [ ] Telemetry: default install = zero outbound traffic. Consent flow documented.
- [ ] `docs/mcp/tools.md` now lists **29 tools** (Phase 4 had 23; Phase 5 adds 6: `list_pipelines`, `explain_pipeline`, `run_pipeline`, `get_wiki_page`, `wiki_search`, `list_patterns`, `get_pattern`, `find_pattern_for` — real `check_conventions` replaces stub).

---

## 8. Files Phase 5 produces / modifies

| File | New / Modified |
|------|----------------|
| `src/pipelines/` | NEW (loader, runner, context) |
| `pipelines/*.yaml` | NEW (5 built-ins) |
| `scripts/build_wiki.py` | NEW |
| `scripts/extract_patterns.py` | NEW |
| `src/mcp/tools/run_pipeline.py` etc. | NEW (8 tools) |
| `src/workspaces.py` | NEW (multi-repo support) |
| `src/telemetry.py` | NEW |
| `config.yaml` | MODIFIED (workspaces, telemetry) |
| `docs/telemetry.md` | NEW |
| `docs/mcp/tools.md` | REGENERATED |

---

*End of Phase 5. Agent Hub is feature-complete for v1.0.*
