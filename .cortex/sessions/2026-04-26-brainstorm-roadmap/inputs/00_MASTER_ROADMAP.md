# Agent Hub — Master Roadmap (v2, decisions baked in)

> **Audience**: coding agents (Roo Code with Nemotron / Mistral / GPT-class) + human reviewers.
> **All output (code, comments, prompts, commits) MUST be in English.**
> **Read this file first**, then jump to the phase document referenced by your task.

---

## 1. Strategic context

Agent Hub is now positioned as **the MCP server for AI coding agents on large, under-documented codebases**.

**The existential constraint**: zero hallucination in MCP tool responses. If a tool returns a class name, a method, a file path, or a module that does not exist in the source, the project is dead. Every architectural choice in this roadmap is subordinated to that constraint.

The seven strategic decisions are recorded in [`docs/decisions/`](../decisions/) (one ADR each) and their consequences flow through this roadmap:

| Decision | Choice | Roadmap impact |
|----------|--------|----------------|
| DECIDE-1 | Extract project pipeline to sister repo | Phase 0 / [`EXTRACT_PROJECTS_REPO.md`](EXTRACT_PROJECTS_REPO.md) |
| DECIDE-2 | Demote `/` chat to `/debug/chat` | Phase 0, T-002 |
| DECIDE-3 | Keep `/v1/chat/completions` as expert-RAG only | Phase 0, T-004 |
| DECIDE-4 | Remove `code` agent + `file_edit` MCP tool | Phase 0, T-003 |
| DECIDE-5 | Invest in GraphRAG | Phase 2 (tree-sitter + AST + LLM hybrid) |
| DECIDE-6 | Multi-repo support in Phase 5 | Phase 5, T-503 |
| DECIDE-7 | Opt-in telemetry | Phase 5, T-504 |
| DECIDE-8 | Fix & enrich changelog | Phase 3 (full rebuild) |

---

## 2. Phase index and dependencies

```
Phase 0 — Cleanup (decisions execution)        [BLOCKING for everything]
   │
   ├─▶ Phase 1 — Anti-Hallucination Hardening  [BLOCKING for Phase 4+]
   │      │
   │      ├─▶ Phase 2 — GraphRAG Investment    [DECIDE-5]
   │      │
   │      ├─▶ Phase 3 — Changelog Fix          [DECIDE-8]
   │      │
   │      └─▶ Phase 4 — MCP Server + Code Intelligence Tools
   │             │
   │             └─▶ Phase 5 — Advanced (Pipelines, Wiki, Multi-repo, Telemetry)
```

| # | Phase | Document | Effort | Status |
|---|-------|----------|--------|--------|
| 0 | Cleanup | this file (§4) | 1 week | [ ] |
| 1 | Anti-Hallucination Hardening | [`01_PHASE_GROUNDING.md`](01_PHASE_GROUNDING.md) | 3 weeks | [ ] |
| 2 | GraphRAG Investment | [`02_PHASE_GRAPHRAG.md`](02_PHASE_GRAPHRAG.md) | 3 weeks | [ ] |
| 3 | Changelog Fix | [`03_PHASE_CHANGELOG.md`](03_PHASE_CHANGELOG.md) | 2 weeks | [ ] |
| 4 | MCP Server + Tools | [`04_PHASE_MCP_TOOLS.md`](04_PHASE_MCP_TOOLS.md) | 4 weeks | [ ] |
| 5 | Advanced features | [`05_PHASE_ADVANCED.md`](05_PHASE_ADVANCED.md) | 4 weeks | [ ] |

**Phases 2 / 3 / 4 are parallelizable** once Phase 1 ships its grounding library (`src/rag/grounding.py`).

---

## 3. How to read a task

Every task in this roadmap follows the template in [`TASK_TEMPLATE.md`](TASK_TEMPLATE.md). A coding agent picking up a task needs ONLY:

1. This master roadmap (for context).
2. The task's phase document.
3. `.roo/rules.md` and `.roo/context.md` (always loaded by Roo modes).
4. The source files mentioned in `FILES`.

If the task is unclear, the agent must ASK rather than guess. See [`.roo/rules.md`](../../.roo/rules.md) §4.

---

## 4. Phase 0 — Cleanup (1 week)

**Goal**: execute the seven strategic decisions. Make the repo tell one story: "MCP server for code intelligence". Remove what contradicts it.

**Order matters**: T-001 (extraction) should ship first because it touches the most files. T-002 through T-005 can run in parallel afterward.

### T-001 — Extract project pipeline to `agent-hub-projects`

**Decision**: DECIDE-1
**Mode**: `deprecator`
**Effort**: 2 days

**CONTEXT**
The greenfield project pipeline (`portfolio → specifier → planner → storyteller → presenter`) is a coherent product but a different one. It targets a different user (PM/architect doing greenfield design) and dilutes the MCP-server message. We extract it to a sister repo while preserving git history.

**FILES TO REMOVE FROM `agent-hub` (after extraction)**

```
src/agents/portfolio.py
src/agents/specifier.py
src/agents/planner.py
src/agents/storyteller.py
src/agents/presenter.py
src/agents/project_agent.py
src/projects.py
src/pipeline.py
src/workspace_session.py
agents/defs/portfolio.md
agents/defs/specifier.md
agents/defs/planner.md
agents/defs/storyteller.md
agents/defs/presenter.md
web/workspace.html
web/workspace_routes.py
projects/                       (entire directory)
```

**FILES TO UPDATE IN `agent-hub`**

| File | Change |
|------|--------|
| `src/main.py` | Remove imports & menu entries for the 5 project agents. Remove `--project` CLI flag. |
| `web/server.py` | Remove `/workspace` route registration and any pipeline endpoints. |
| `run.py` | Remove `--project` argument and pipeline branches. |
| `config.yaml` | Remove `agents.portfolio`, `.specifier`, `.planner`, `.storyteller`, `.presenter` sections. |
| `README.md` | Remove "Project Pipeline" section. Add a one-line note: "For greenfield project authoring, see [agent-hub-projects](https://github.com/GrIc/agent-hub-projects)." |

**EXECUTION**

Use the script [`scripts/extract_projects.sh`](../../scripts/extract_projects.sh). Read the [`EXTRACT_PROJECTS_REPO.md`](EXTRACT_PROJECTS_REPO.md) guide for prerequisites and rollback instructions.

**ACCEPTANCE**
- New repo `agent-hub-projects` exists with intact git history for the extracted files.
- `agent-hub` repo: `find agents/defs -name "*.md"` returns ONLY `expert.md`, `codex.md`, `documenter.md`, plus any user-added custom agents.
- `agent-hub` repo: `python run.py --help` shows no `--project` flag.
- `docker compose up -d` starts cleanly with no errors.
- All existing tests still pass (or are removed if they only tested removed code).

**ANTI-PATTERNS**
- Do NOT just `git rm` — use `git filter-repo` to keep history in the new repo.
- Do NOT leave commented-out imports or dead branches "in case we change our mind".
- Do NOT skip updating `README.md` and `config.yaml` — they are part of the contract.

---

### T-002 — Demote `/` chat to `/debug/chat`

**Decision**: DECIDE-2
**Mode**: `deprecator`
**Effort**: 0.5 day

**CONTEXT**
The home-page chat at `/` competes with Open WebUI (already integrated). Keeping it as the front door confuses users about the product. We demote it to a debug tool but keep it for inspecting retrieval results.

**FILES TO MODIFY**

| File | Change |
|------|--------|
| `web/server.py` | Change route from `/` to `/debug/chat`. Add a redirect from `/` to a new `/admin` landing page (delivered in T-005). |
| `web/index.html` | Add a banner at the top: `<div class="banner">⚠️ Debug UI — for daily chat use Open WebUI at :3000. This page exists only for inspecting retrieval results and source citations.</div>`. Update the `<title>` to `Agent Hub — Debug Chat`. |
| `README.md` | Remove any "open `/` for chat" mention. Reference Open WebUI instead. |

**ADDITIONAL REQUIREMENT**
The debug chat must show **expanded source citations** for every assistant response: file path, line range, doc level, and a click-to-expand snippet. This is its new primary value (debugging retrieval, not chatting).

**ACCEPTANCE**
- Visiting `http://localhost:8080/` redirects to `/admin` (or shows a placeholder until T-005 ships).
- Visiting `http://localhost:8080/debug/chat` shows the chat with the new banner and expanded source citations.
- README does not invite users to use the in-repo chat.

**ANTI-PATTERNS**
- Do NOT remove the page entirely — it has debug value.
- Do NOT leave `/` returning the chat (confuses external monitors / health probes).

---

### T-003 — Remove `code` agent and `file_edit` MCP tool

**Decision**: DECIDE-4
**Mode**: `deprecator`
**Effort**: 1 day

**CONTEXT**
Cline, Roo Code, Claude Code, and Cursor all do file editing natively and better. The `code` agent + `file_edit` MCP tool were attempts to compete on edit semantics — we cede that ground and focus on knowledge.

**FILES TO REMOVE**

```
src/agents/code.py
agents/defs/code.md
src/mcp/tools/file_edit.py        (or remove the tool block from src/mcp_server.py)
```

**FILES TO MODIFY**

| File | Change |
|------|--------|
| `src/main.py` | Remove `code` agent registration + the commands `/apply`, `/diff`, `/diffs`, `/show`. |
| `src/mcp_server.py` | Remove the `file_edit` tool definition + handler. |
| `config.yaml` | Remove `agents.code` section. |
| `README.md` | Remove the `code` agent row from the agents table. Remove `file_edit` from the MCP tools table. |
| `output/` directory | Delete it entirely (it stored generated diffs from the `code` agent). |

**ACCEPTANCE**
- `python run.py --agent code` returns "unknown agent" error.
- MCP `list_tools` does NOT contain `file_edit`.
- `grep -r "file_edit\|/apply\|/diff " --include="*.py" --include="*.md" .` returns only this task's removal mentions.

**ANTI-PATTERNS**
- Do NOT replace `file_edit` with another file-editing tool. Do not implement `apply_patch` or similar. We are out of that business.
- Do NOT keep the agent "for backward compat" — break the contract cleanly, the consumers are explicit MCP clients that read `list_tools`.

---

### T-004 — Refocus `/v1/chat/completions` as `expert-rag` model only

**Decision**: DECIDE-3
**Mode**: `roadmap-executor`
**Effort**: 1 day

**CONTEXT**
We keep the OpenAI-compatible endpoint but stop exposing every internal agent as a "model". Only one model name is exposed: `expert-rag` — the RAG-augmented expert agent. This makes the endpoint's purpose unambiguous: "give a chat client RAG-grounded answers".

**FILES TO MODIFY**

| File | Change |
|------|--------|
| `web/server.py` (or the chat-completions router) | The `/v1/models` endpoint returns ONLY `[{"id": "expert-rag", "object": "model"}]`. The `/v1/chat/completions` endpoint accepts ONLY `model: "expert-rag"` — any other value returns `404 model_not_found`. |
| `README.md` § IDE Integration | Update Roo Code / Continue.dev setup instructions: `Model = expert-rag` (not `expert`, `documenter`, etc.). |
| `continue-sse.yaml`, `continue-stdio.yaml` | Update model name to `expert-rag`. |
| `docs/clients/*.md` (created in T-005) | Same model name. |

**Implementation note**: internally, `expert-rag` is the existing `expert` agent. Just rename the public-facing identifier; do not refactor the agent itself.

**ACCEPTANCE**
- `curl http://localhost:8080/v1/models` returns exactly one model: `expert-rag`.
- `curl -X POST .../v1/chat/completions -d '{"model":"documenter",...}'` returns 404.
- `curl -X POST .../v1/chat/completions -d '{"model":"expert-rag",...}'` returns a valid completion.

**ANTI-PATTERNS**
- Do NOT remove the OpenAI-compat endpoint entirely (consumers like Roo chat mode use it).
- Do NOT expose internal agents (codex, documenter, etc.) as models — they are MCP tools, not chat models.

---

### T-005 — Rewrite README + restructure `docs/`

**Decision**: positioning consequence of all decisions
**Mode**: `roadmap-executor`
**Effort**: 1 day

**CONTEXT**
The README still pitches Agent Hub as a "multi-agent system with RAG". The new pitch is "MCP server for AI coding agents on large codebases". The doc tree should reflect this.

**NEW `README.md` STRUCTURE**

```
# Agent Hub
> The MCP server that gives AI coding agents senior-engineer-level knowledge of your codebase.

## Why
- Large codebases (100k–10M LOC) have knowledge in 5 layers (text, structure, semantics, conventions, history).
  Coding agents see only layer 1. Agent Hub exposes layers 2–5 as MCP tools.

## Quick start (5 commands)
1. clone
2. cp .env.example .env  # set API_KEY + API_BASE_URL
3. ln -s /path/to/your/code workspace
4. docker compose up -d
5. point your MCP client at http://localhost:8080/mcp/sse

## What you get
- 29 MCP tools across 8 categories (see docs/mcp/tools.md, link)
- Auto-generated wiki at /wiki
- Daily changelog with semantic summaries
- Pattern & convention discovery
- Call graph + impact preview
- Custom YAML pipelines

## Documentation
- [Architecture](docs/architecture.md)
- [MCP tools reference](docs/mcp/tools.md)
- [Client setups](docs/clients/) — Cline, Roo, Claude Code, Cursor, Continue.dev
- [Operations](docs/operations/) — deploy, scale, troubleshoot
- [Decisions (ADRs)](docs/decisions/)
- [Roadmap](docs/roadmap/00_MASTER_ROADMAP.md)
```

**NEW `docs/` LAYOUT**

```
docs/
├── architecture.md             ← system overview (replaces scattered text)
├── vision.md                   ← short positioning
├── mcp/
│   └── tools.md                ← auto-generated reference (Phase 4 will produce it)
├── clients/
│   ├── cline.md
│   ├── claude-code.md
│   ├── roo-code.md
│   ├── cursor.md
│   └── continue.md
├── operations/
│   ├── deploy.md
│   ├── troubleshoot.md
│   └── scale.md
├── decisions/                  ← ADRs (one per DECIDE-*)
│   ├── 0001-extract-projects.md
│   ├── 0002-demote-chat.md
│   ├── 0003-expert-rag-only.md
│   ├── 0004-remove-code-agent.md
│   ├── 0005-invest-graphrag.md
│   ├── 0006-multi-repo-phase5.md
│   ├── 0007-opt-in-telemetry.md
│   └── 0008-fix-changelog.md
└── roadmap/                    ← THIS DIRECTORY
```

**ACCEPTANCE**
- README is under 200 lines and matches the structure above.
- All `docs/decisions/*.md` files exist with: Context, Options considered, Decision, Consequences (4 sections, 1 page max each).
- `grep -r "multi-agent system with RAG" .` returns zero hits.
- A first-time visitor can state the product's purpose in one sentence after reading the README.

**ANTI-PATTERNS**
- Do NOT keep both old and new README content "for transition".
- Do NOT write 5-page ADRs — 1 page each is plenty.

---

## 5. Phase 0 success gate

Before starting Phase 1, the following MUST be true:

- [ ] T-001 through T-005 merged.
- [ ] `agent-hub-projects` repo exists and builds.
- [ ] `find agents/defs -name "*.md" | sort` returns: `codex.md`, `documenter.md`, `expert.md` (+ user customs).
- [ ] `docker compose up -d && curl localhost:8080/healthz` returns 200.
- [ ] README pitches "MCP server", not "multi-agent system".
- [ ] `docs/decisions/` contains 8 ADRs (one per DECIDE-*).
- [ ] `.roo/rules.md`, `.roo/context.md`, and `.roomodes` are in place (see [`ROO_SETUP.md`](ROO_SETUP.md)).

If any item is missing, do not proceed.

---

## 6. Cross-phase quality gates

These rules apply to **every** task in **every** phase. They are restated in `.roo/rules.md` and enforced by Roo modes.

1. **Source grounding**: every name (class, method, file, module) referenced in any LLM-generated output MUST be verifiable in the source. Validation rules in [`01_PHASE_GROUNDING.md`](01_PHASE_GROUNDING.md).
2. **Citation contract**: every MCP tool that returns code-related information MUST include a `sources: [{path, line_start, line_end}]` field. Tools fail closed if sources cannot be produced.
3. **Abstain over guess**: when an LLM cannot ground an answer, it returns `INSUFFICIENT_EVIDENCE`. The MCP tool then returns an empty result with `notes: "..."`, never a fabricated guess.
4. **Schema validation**: every MCP tool input is validated against JSON Schema before invocation. Every output is validated against its declared output schema. Failures return a structured error envelope.
5. **English only**: all generated text — code, comments, prompts, log messages, agent definitions, doc strings — is in English. No exceptions.
6. **Config over code**: new behaviors are exposed as `config.yaml` keys with documented defaults. No hardcoded magic.
7. **Complete file replacement**: deliverables are full files, not patches/diffs. (Per user preference; patches fail too often with weaker models.)
8. **Test-first for tools**: a new MCP tool MUST ship with a golden test exercising the input/output contract.
9. **Changelog discipline**: every PR adds an entry to `CHANGELOG.md` (Keep a Changelog format).
10. **No new dependencies without approval**: if a task requires a new pip package, it must be flagged in the PR description and approved separately.

---

## 7. Estimated timeline

Assuming one full-time engineer-equivalent of effort (you + Roo agents):

| Phase | Effort | Cumulative |
|-------|--------|------------|
| Phase 0 | 1 week | 1 week |
| Phase 1 | 3 weeks | 4 weeks |
| Phase 2 | 3 weeks ⇄ Phase 3 | 7 weeks |
| Phase 3 | 2 weeks ⇄ Phase 2 | 7 weeks |
| Phase 4 | 4 weeks | 11 weeks |
| Phase 5 | 4 weeks | 15 weeks |

Realistic with parallelization: **15–18 weeks** to feature complete.

---

## 8. Where to find what

| Topic | Location |
|-------|----------|
| Decisions (ADRs) | `docs/decisions/0001-...md` to `0008-...md` |
| Roadmap (this) | `docs/roadmap/00_MASTER_ROADMAP.md` |
| Per-phase tasks | `docs/roadmap/0X_PHASE_*.md` |
| Roo Code rules | `.roo/rules.md` |
| Roo Code context | `.roo/context.md` |
| Roo Code custom modes | `.roomodes` (repo root) |
| Task template | `docs/roadmap/TASK_TEMPLATE.md` |
| Extraction guide | `docs/roadmap/EXTRACT_PROJECTS_REPO.md` |
| Roo setup walkthrough | `docs/roadmap/ROO_SETUP.md` |
| Skills (Roo) | `.roo/skills/` (created in Phase 1) |

---

*End of master roadmap. Proceed to your phase document.*
