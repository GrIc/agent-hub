# Agent Hub — Master Roadmap (v2.1, strategy + horizon 2)

> **Audience**: coding agents (Roo Code) + human reviewers.
> **All output (code, comments, prompts, commits) MUST be in English.**
> **Read order**: [`STRATEGY.md`](STRATEGY.md) → this file → your phase document.

---

## 1. Strategic context (one-paragraph version)

Agent Hub is **the trust substrate for autonomous code**. As AI coding agents (Cline, Roo, Claude Code, Cursor) get faster than human review, the scarce resource is trust. Agent Hub delivers trust through four pillars — Grounding, Citations, Verification, Simulation — each a concrete engineering deliverable, each phase of this roadmap. The existential constraint is zero hallucination in MCP tool responses. Every architectural choice is subordinated to that constraint.

**Full strategy**: [`STRATEGY.md`](STRATEGY.md). Read it before anything else.

---

## 2. Strategic decisions

The roadmap executes 10 strategic decisions, each documented as an ADR in [`docs/decisions/`](../decisions/).

| Decision | Choice | Roadmap impact |
|----------|--------|----------------|
| DECIDE-1 | Extract project pipeline to sister repo | Phase 0 / [`EXTRACT_PROJECTS_REPO.md`](EXTRACT_PROJECTS_REPO.md) |
| DECIDE-2 | Demote `/` chat to `/debug/chat` | Phase 0, T-002 |
| DECIDE-3 | Keep `/v1/chat/completions` as expert-RAG only | Phase 0, T-004 |
| DECIDE-4 | Remove `code` agent + `file_edit` MCP tool | Phase 0, T-003 |
| DECIDE-5 | Invest in GraphRAG | Phase 2 (tree-sitter + AST + LLM hybrid) |
| DECIDE-6 | Multi-repo support in Phase 5 | Phase 5 |
| DECIDE-7 | Opt-in telemetry | Phase 5 + Phase 7 world model |
| DECIDE-8 | Fix & enrich changelog | Phase 3 |
| **DECIDE-9** | **Reposition as "trust substrate for autonomous code"** | All phases; positioning rewrite in T-005b |
| **DECIDE-10** | **Adopt neuro-symbolic verification (Z3) as first-class capability** | Phase 6 |

---

## 3. Phase index and dependencies

```
Phase 0 — Cleanup                                    [BLOCKING]
   │
   ├─▶ Phase 1 — Grounding                           [BLOCKING for 4, 6, 7]
   │      │
   │      ├─▶ Phase 2 — GraphRAG                     [enables 6 + 7A]
   │      │
   │      ├─▶ Phase 3 — Changelog                    [enables 7A risk scoring]
   │      │
   │      └─▶ Phase 4 — MCP Framework + 23 tools
   │             │
   │             ├─▶ Phase 5 — Advanced (pipelines, wiki, multi-repo, telemetry)
   │             │
   │             └─▶ Phase 6 — Verifiable Autonomy   ← v2.0 SHIPS
   │                    │
   │                    └─▶ Phase 7 — Adaptive Intelligence  ← v3.0 SHIPS
```

### Phase inventory

| # | Phase | Document | Effort | Target version |
|---|-------|----------|--------|----------------|
| 0 | Cleanup | this file §6 | 1 week | v1.0-rc |
| 1 | Anti-Hallucination | [`01_PHASE_GROUNDING.md`](01_PHASE_GROUNDING.md) | 3 weeks | v1.0-rc |
| 2 | GraphRAG | [`02_PHASE_GRAPHRAG.md`](02_PHASE_GRAPHRAG.md) | 3 weeks | v1.0 |
| 3 | Changelog | [`03_PHASE_CHANGELOG.md`](03_PHASE_CHANGELOG.md) | 2 weeks | v1.0 |
| 4 | MCP Server + Tools | [`04_PHASE_MCP_TOOLS.md`](04_PHASE_MCP_TOOLS.md) | 4 weeks | v1.0 |
| 5 | Advanced | [`05_PHASE_ADVANCED.md`](05_PHASE_ADVANCED.md) | 4 weeks | v1.0 |
| **6** | **Verifiable Autonomy** | [`06_PHASE_VERIFIABLE_AUTONOMY.md`](06_PHASE_VERIFIABLE_AUTONOMY.md) | 9 weeks | **v2.0** |
| **7** | **Adaptive Intelligence** | [`07_PHASE_ADAPTIVE_INTELLIGENCE.md`](07_PHASE_ADAPTIVE_INTELLIGENCE.md) | 16+ weeks | **v3.0** |

Phases 2 / 3 / 4 are parallelizable after Phase 1. Phase 6 can start in parallel with Phase 5 once Phase 4's framework is stable.

---

## 4. Release milestones

| Release | Scope | Target week | Definition of done |
|---------|-------|-------------|--------------------|
| **v1.0** | Phases 0-5 | 15 | Hallucination rate < 2%; 23 MCP tools pass golden tests; 5 pipelines run end-to-end |
| **v2.0** | + Phase 6 | 24 | 10 built-in policies; `verify_change` catches known violations with counterexamples; 0 false positives on user's workspace in 1-week soak |
| **v3.0** | + Phase 7 | 40+ | Regression predictor AUC > 0.7 on user data; credit scoring auto-quarantines a deliberately-broken tool; 1 evolved prompt approved and merged |

Each milestone is independently shippable. Stopping at any milestone is a successful outcome.

---

## 5. How to read a task

Every task follows the template in [`TASK_TEMPLATE.md`](TASK_TEMPLATE.md).

A coding agent executing a task needs ONLY:
1. [`STRATEGY.md`](STRATEGY.md) (for the why).
2. This master roadmap (for the where).
3. The task's phase document (for the what).
4. [`.roo/rules.md`](../../.roo/rules.md) and [`.roo/context.md`](../../.roo/context.md).
5. The source files mentioned in the task's `FILES` section.
6. Any Roo skill loaded by the task's mode.

If the task is unclear, the agent must ASK rather than guess.

---

## 6. Phase 0 — Cleanup (execution of decisions)

**Goal**: execute the ten strategic decisions. Make the repo tell one coherent story: "trust substrate for autonomous code".

**Order matters**: T-001 (extraction) first. T-002 through T-005b can run in parallel afterward.

### T-001 — Extract project pipeline to `agent-hub-projects`

**Decision**: DECIDE-1
**Mode**: `deprecator`
**Effort**: 2 days
**Guide**: [`EXTRACT_PROJECTS_REPO.md`](EXTRACT_PROJECTS_REPO.md)
**Script**: [`../../scripts/extract_projects.sh`](../../scripts/extract_projects.sh)

### T-002 — Demote `/` chat to `/debug/chat`

**Decision**: DECIDE-2
**Mode**: `deprecator`
**Effort**: 0.5 day

Route changes + banner + expanded source citations for debugging retrieval.

### T-003 — Remove `code` agent and `file_edit` MCP tool

**Decision**: DECIDE-4
**Mode**: `deprecator`
**Effort**: 1 day

Clean removal: files deleted, imports cleaned, config cleaned, docs cleaned, tests cleaned.

### T-004 — Refocus `/v1/chat/completions` as `expert-rag` only

**Decision**: DECIDE-3
**Mode**: `roadmap-executor`
**Effort**: 1 day

Expose exactly one model (`expert-rag`), reject all other model names with 404.

### T-005 — Rewrite README + restructure `docs/`

**Decision**: positioning consequence
**Mode**: `roadmap-executor`
**Effort**: 1 day

New README ≤ 200 lines, matching the "trust substrate" positioning. New `docs/` layout.

### T-005b — Align all positioning copy with v2 strategy (NEW in v2.1)

**Decisions**: DECIDE-9, DECIDE-10
**Mode**: `roadmap-executor`
**Effort**: 0.5 day
**Depends on**: T-005.

**CONTEXT**
T-005 removed the "multi-agent system" framing. T-005b installs the new one: "trust substrate for autonomous code" with the four pillars.

**FILES**

- `README.md` — intro section rewritten per [`STRATEGY.md`](STRATEGY.md) §1-2. First sentence: "Agent Hub makes AI-written code trustworthy enough to ship, at the pace AI writes it." Then the four pillars diagram. Then quick-start.
- `docs/vision.md` — short pointer to `STRATEGY.md`.
- `docs/decisions/0009-trust-substrate.md` — ADR (template below).
- `docs/decisions/0010-neuro-symbolic.md` — ADR (template below).

**ADR 0009 template**:
```
# 0009 — Reposition as the trust substrate for autonomous code

## Context
AI coding agents are outpacing human review. Our previous framing ("MCP server for coding agents on large codebases") is correct but undersells the strategic opportunity.

## Options considered
A. Keep current positioning. Safe but ceiling-limited.
B. Reposition as "trust substrate for autonomous code" with 4 pillars (grounding, citations, verification, simulation).
C. Reposition as an enterprise AI governance platform. Too big, loses focus.

## Decision
B.

## Consequences
- Phases 6-7 added to roadmap (verification, world model).
- All positioning copy rewritten.
- New primary persona: regulated-industry platform teams.
- Sales conversations start with the trust problem, not the tool list.
```

**ADR 0010 template**:
```
# 0010 — Adopt neuro-symbolic verification (Z3) as a first-class capability

## Context
Grounding + citations eliminate hallucinations in information. They do NOT prove that a proposed change respects the codebase's invariants. For regulated-industry adoption, the system must verify, not just inform.

## Options considered
A. Hope human reviewers catch invariant violations. Doesn't scale, doesn't differentiate.
B. Build a rules engine that pattern-matches "bad" code. Heuristic, brittle, noisy.
C. Integrate an SMT solver (Z3). Mathematical, explainable via counterexamples, extensible via policy DSL.

## Decision
C.

## Consequences
- Phase 6 scope defined: solver, policy DSL, fact extractors, pipeline, 3 new MCP tools.
- New Roo mode `verifier-engineer` and skill `neuro-symbolic.md`.
- New pip dependency: `z3-solver`. Justified by the capability unlock.
- Enables the "v2.0" milestone: the first version we can sell to regulated industries.
```

**ACCEPTANCE**
- First-time visitor can describe Agent Hub as "the trust substrate for AI coding agents" after reading the README intro.
- ADRs 0009 and 0010 exist and are ≤ 1 page each.
- `grep -r "multi-agent" .` returns zero hits outside of changelog/decision history.

**ANTI-PATTERNS**
- Do NOT turn `STRATEGY.md` into the README. They serve different audiences.
- Do NOT add new marketing claims the roadmap doesn't back up.

---

### Phase 0 success gate

Before starting Phase 1, the following MUST be true:

- [ ] T-001 through T-005b merged.
- [ ] `agent-hub-projects` repo exists and builds.
- [ ] `find agents/defs -name "*.md" | sort` returns only `codex.md`, `documenter.md`, `expert.md` (+ user customs).
- [ ] `docker compose up -d && curl localhost:8080/healthz` returns 200.
- [ ] README pitches "trust substrate", not "multi-agent system".
- [ ] `docs/decisions/` contains 10 ADRs (0001 through 0010).
- [ ] [`STRATEGY.md`](STRATEGY.md), `.roo/rules.md`, `.roo/context.md`, `.roomodes` are all in place (see [`ROO_SETUP.md`](ROO_SETUP.md)).

If any item is missing, do not proceed.

---

## 7. Cross-phase quality gates (v2)

Carried forward from v1 + additions for Phases 6-7:

1. **Source grounding**: every LLM-generated name is verifiable in source.
2. **Citation contract**: every MCP tool returns verifiable `sources`.
3. **Abstain over guess**: `[INSUFFICIENT_EVIDENCE]` is always preferred to fabrication.
4. **Schema validation**: every MCP I/O validated against JSON Schema.
5. **English only**: all generated text in English.
6. **Config over code**: new behaviors in `config.yaml`.
7. **Complete file replacement**: deliverables are full files.
8. **Test-first for tools**: every MCP tool ships with a golden test.
9. **Changelog discipline**: every PR adds a `CHANGELOG.md` entry.
10. **No new dependencies without approval**: new pip/npm packages flagged in PR.
11. **(v2) Verification fails closed**: verifier timeout or error → `unknown`, never `pass`.
12. **(v2) Telemetry is opt-in**: no outbound traffic by default; verified in CI network audit.
13. **(v2) Predictions include confidence**: world model outputs always carry a training-data-adequacy flag.
14. **(v2) Self-evolution stays in shadow**: prompt variants are proposed, never auto-applied.

---

## 8. Estimated timeline

| Phase | Effort | Cumulative | Version |
|-------|--------|------------|---------|
| Phase 0 | 1 week | 1 week | — |
| Phase 1 | 3 weeks | 4 weeks | — |
| Phase 2 | 3 weeks ⇄ Phase 3 | 7 weeks | — |
| Phase 3 | 2 weeks ⇄ Phase 2 | 7 weeks | — |
| Phase 4 | 4 weeks | 11 weeks | — |
| Phase 5 | 4 weeks | 15 weeks | **v1.0** |
| Phase 6 | 9 weeks | 24 weeks | **v2.0** |
| Phase 7 | 16+ weeks | 40+ weeks | **v3.0** |

With parallelization: v1.0 in **~15 weeks**, v2.0 in **~24 weeks**, v3.0 in **40+ weeks** (uncertain horizon).

---

## 9. Where to find what

| Topic | Location |
|-------|----------|
| Strategy (North Star) | [`STRATEGY.md`](STRATEGY.md) |
| Decisions (ADRs) | `docs/decisions/0001-...md` to `0010-...md` |
| Roadmap index | this file |
| Per-phase tasks | `docs/roadmap/0X_PHASE_*.md` |
| Roo Code rules | `.roo/rules.md` |
| Roo Code context | `.roo/context.md` |
| Roo Code custom modes | `.roomodes` (repo root) |
| Task template | `docs/roadmap/TASK_TEMPLATE.md` |
| Extraction guide | `docs/roadmap/EXTRACT_PROJECTS_REPO.md` |
| Roo setup walkthrough | `docs/roadmap/ROO_SETUP.md` |
| Roo skills | `.roo/skills/` |

### Roo skills catalog (v2)

| Skill | Loaded by | Purpose |
|-------|-----------|---------|
| `grounding.md` | `kip-engineer`, `graph-engineer`, `mcp-engineer`, `verifier-engineer` | Anti-hallucination patterns |
| `ast-extraction.md` | `graph-engineer`, `verifier-engineer` | Tree-sitter patterns |
| `mcp-framework.md` | `mcp-engineer` | MCP tool patterns |
| **`neuro-symbolic.md`** | **`verifier-engineer`** | **Z3 + policy + fact-extraction patterns** |

### Roo modes catalog (v2)

| Mode | Role |
|------|------|
| `roadmap-executor` | Generic default |
| `kip-engineer` | Grounding / anti-hallucination |
| `graph-engineer` | AST + graph |
| `mcp-engineer` | MCP framework + tools |
| `deprecator` | Clean removal |
| `changelog-doctor` | T-301 diagnostic only |
| **`verifier-engineer`** | **Phase 6: Z3, policies, verification tools** |

---

## 10. If you only have 30 seconds

- **What we are**: the trust substrate for autonomous code.
- **Why it wins**: AI agents get faster; trust is the bottleneck; we replace review with proof.
- **Where we invest**: grounding (Phase 1), structural graph (Phase 2), cited tools (Phase 4), formal verification (Phase 6), adaptive intelligence (Phase 7).
- **Where we do NOT invest**: code editors, chat UIs, cloud SaaS, general-purpose LLM gateways, ZKP infrastructure.
- **First gate**: Phase 1 < 2% hallucination. Everything else is built on top.

---

*End of master roadmap. Proceed to your phase document.*
