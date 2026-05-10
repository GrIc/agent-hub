# Phase 7 — Adaptive Intelligence (World Model, Immune System, Self-Evolution)

> **Mode**: `verifier-engineer` + `graph-engineer` + `roadmap-executor`.
> **Effort**: 16+ weeks (weeks 25-40+ in master timeline).
> **Prerequisite**: Phase 6 complete AND at least 30 days of production telemetry from the user's workspace.
> **Horizon**: this is **horizon-2 research territory**. Scope and timeline are less certain than Phases 0-6. Treat as a direction, not a contract.

---

## 1. What Phase 7 delivers

Three workstreams, each independently valuable. They can be built sequentially or in parallel depending on engineering capacity.

| # | Workstream | Outcome | Certainty |
|---|-----------|---------|-----------|
| A | **World Model** | Regression prediction from telemetry-enriched graph. The `simulate_change` tool goes from "affected modules" to "predicted behavioral delta + failure probability". | Medium |
| B | **Digital Immune System (lite)** | MCP tool capability registry with behavioral credit scoring. Tools that misbehave get auto-quarantined; new tools start with low trust and earn credit. | Medium |
| C | **Self-evolving prompts** | Shadow-mode prompt optimization via MAP-Elites. Never auto-applied — only proposed for human approval. | Low (research) |

Phase 7 is how Agent Hub becomes not just trustworthy but **adaptive** — learning from the running system rather than only from static analysis.

---

## 2. Workstream A — World Model

### 2.1 Context

A code graph is a snapshot of structure. A **world model** is a snapshot of *behavior*: which edges carry runtime traffic, which nodes fail together, which paths account for latency. Combining structure + behavior enables a new tool: **predict regression before it ships**.

Sources of behavioral signal:
- Production telemetry (logs, traces, metrics) — if the user has Prometheus / OpenTelemetry / similar.
- CI logs (test pass/fail history per commit).
- Incident tickets (Jira, GitLab issues) with links to commits.
- The temporal store (Phase 3) already knows which files change together.

### 2.2 Tasks (workstream A)

#### T-701 — Telemetry connector

**Effort**: 4 days
**Mode**: `verifier-engineer`

**FILES**: `src/world/telemetry/`

Connectors for the three sources the user indicates they have. Start with:
- `prometheus.py` — periodic scrape of metrics, mapped to graph nodes by naming convention or user-supplied rules.
- `opentelemetry.py` — trace ingestion; each trace span annotates the edges it traverses.
- `ci_logs.py` — CI runs + test outcomes, indexed by commit SHA.

Config:
```yaml
world_model:
  enabled: false                    # default OFF (opt-in, per DECIDE-7)
  telemetry:
    prometheus:
      url_env: PROMETHEUS_URL
      scrape_interval_s: 60
    otel:
      collector_url_env: OTEL_COLLECTOR_URL
    ci:
      gitlab_api_env: GITLAB_API_URL
```

Every telemetry source: opt-in, self-hosted endpoints only, no data leaves the customer's environment.

**Acceptance**:
- Each connector can be tested end-to-end with a mock server.
- Scraped data persists in `context/world_model/observations.sqlite`.
- Zero signal lost on connector restart (resume from last timestamp).

#### T-702 — Enrich graph edges with runtime weight

**Effort**: 3 days
**Mode**: `graph-engineer`

**FILES**: modify `src/graph/store.py` to support `runtime_weight` on edges (not replacing structural weight; adding a second column).

Runtime weight is derived from telemetry:
- `calls` edge: proportional to observed call frequency.
- `reads/writes` edges: proportional to observed access frequency.
- `depends_on`: proportional to co-failure rate.

Edges with no observations stay at their structural weight. The `preview_impact` tool (Phase 4) now weights by `structural * 0.3 + runtime * 0.7` when runtime data exists.

**Acceptance**:
- On a synthetic workload, `preview_impact` correctly identifies the highest-traffic paths.

#### T-703 — Regression predictor

**Effort**: 8 days
**Mode**: `verifier-engineer`

**CONTEXT**
A statistical model (not a deep learning model — lightweight, interpretable) predicting `P(regression | change)` given:
- Change features (file count, line count, hub-touch, cyclomatic-complexity delta, policy-verification verdict).
- Historical features (past incidents for these files, test flakiness, change frequency).
- Telemetry features (traffic weight of affected paths, recent stability).

Start with **gradient-boosted trees** (xgboost or lightgbm). The model is:
- Trained on the user's own history (commits → incident outcomes).
- Re-trained weekly.
- **Never shared between installations** — each customer's model stays on-prem.

**FILES**: `src/world/predict/`:
- `features.py` — feature extraction from a patch.
- `model.py` — train/predict wrapper.
- `evaluate.py` — hold-out AUC, feature importance report.

Integrate into `simulate_change` as a new output field: `predicted_regression_probability: 0..1`. Only populated when `world_model.enabled` AND enough training data.

**Acceptance**:
- On the user's historical data, AUC > 0.7 on held-out last 30 days.
- Feature importance report is coherent (hub-touch, change size, test coverage all rank high).
- When insufficient data, the field is absent (not 0, not a guess).

**Anti-patterns**:
- Do NOT use deep learning. Interpretability matters for regulated buyers.
- Do NOT ship a pretrained model. Each customer trains from their own history.
- Do NOT auto-block merges based on the prediction. It's informational; humans decide.

#### T-704 — `predict_regression` MCP tool

**Effort**: 1 day

Exposes the predictor. Standard MCP tool contract. Returns abstain if insufficient training data.

---

## 3. Workstream B — Digital Immune System (lite)

### 3.1 Context

As the MCP tool surface grows (user-authored tools, cross-workspace federation, community-contributed tools), we need a mechanism to prevent a misbehaving tool from corrupting the trust contract.

The heavy version (WASM sandboxing + cryptographic capabilities) is overkill for single-tenant self-hosted. The **lite version** is a capability registry with behavioral credit scoring:

- Every tool has a **credit score** (0-100).
- Credit decreases when the tool: produces citation failures, times out, returns schema violations, or is flagged by the user via a thumbs-down endpoint.
- Credit increases with successful calls.
- Tools below a threshold (e.g. < 30) are **auto-quarantined** — listed but not callable until human review.
- New tools start at 50 (neutral).

This is enough to catch regressions from prompt changes, malicious contributions, or buggy user customizations.

### 3.2 Tasks (workstream B)

#### T-711 — Tool registry with credit scoring

**Effort**: 3 days
**Mode**: `mcp-engineer`

**FILES**:
- `src/mcp/registry.py`: extend with `credit_score`, `last_updated`, `quarantined` per tool.
- `src/mcp/middleware/credit.py`: middleware that adjusts score on each call outcome.
- `src/mcp/tools/admin_credit.py`: admin MCP tool for inspecting and manually adjusting scores.

**Scoring deltas**:
- Success: +0.5
- Rate limited: 0
- Invalid input: 0 (caller's fault)
- Invalid output: -2
- Citation failure: -5
- Internal error: -3
- Human thumbs-down (via admin UI): -10

Clamp to 0-100. Quarantine threshold: 30.

**Acceptance**:
- On a synthetic test: a tool that returns bad citations 10 times in a row gets quarantined.
- Admin can override the score and un-quarantine.
- Quarantined tools still appear in `list_tools` with a `quarantined: true` flag.

**Anti-patterns**:
- Do NOT use the credit score to reject individual calls; only to quarantine.
- Do NOT persist scores across restarts in a fragile way — SQLite, same pattern as other stores.

#### T-712 — Anomaly detection (shadow mode)

**Effort**: 3 days

Detect unusual patterns in tool call histories (sudden latency spikes, response-size outliers, citation-failure bursts). Emit warnings to `/admin/anomalies`. **No automatic action** in Phase 7; the feature exists to surface signal, not to act on it.

**Acceptance**:
- On an injected anomaly (latency 10x baseline for 5 minutes), the admin dashboard shows an alert within 10 minutes.

---

## 4. Workstream C — Self-Evolving Prompts (shadow mode)

### 4.1 Context

Agent definitions (`agents/defs/*.md`) and prompt templates (`src/rag/grounding.py::GROUNDING_INSTRUCTION`) are manually authored. Over time, better variants exist but are undiscovered. Phase 7 introduces a **shadow-mode evolution loop**:

- Periodically generate prompt variants (via LLM).
- Run each variant on a held-out evaluation set (golden tests + custom eval corpus).
- Measure quality (hallucination rate, citation validity, abstain rate).
- **Propose** the best variant to the human via a PR-like interface. Never auto-apply.

This is research-grade. It may produce nothing useful. That's OK — the cost is low, and when it works, the wins compound.

### 4.2 Tasks (workstream C)

#### T-721 — Prompt variant generator

**Effort**: 4 days
**Mode**: `verifier-engineer`

**FILES**: `src/evolve/`:
- `generator.py` — given a base prompt, produce N variants (LLM call with a meta-prompt like "rephrase this prompt preserving intent but optimizing for X").
- `evaluator.py` — run a prompt variant against the golden test set, return metrics.
- `selector.py` — MAP-Elites-style archive of (variant, metric_vector) tuples; select best per niche.

**Acceptance**:
- Generator produces 10 variants of a seed prompt, all syntactically valid.
- Evaluator returns reproducible metrics.
- After N iterations, at least 1 proposed variant beats the baseline on at least 2 metrics.

**Anti-patterns**:
- Do NOT automatically apply any variant. Always proposed, never applied.
- Do NOT let the evolver touch the GROUNDING_INSTRUCTION without extra safeguards (bump G_VERSION, re-run all golden tests, require human sign-off).

#### T-722 — Evolution proposal UI

**Effort**: 2 days

A simple `/admin/proposals` page showing: proposed prompts, their metrics vs baseline, a diff view, an "approve" button that opens a PR (`git branch + commit + push`, user merges manually).

**Acceptance**:
- UI lists proposals.
- Clicking approve creates a branch `evolve/<timestamp>` with the proposed change.
- PR description includes metrics.

---

## 5. Phase 7 success gate

- [ ] Workstream A: regression predictor achieves AUC > 0.7 on held-out user data; `predict_regression` tool ships.
- [ ] Workstream B: credit scoring catches a deliberately-broken tool in a synthetic test; `/admin/anomalies` dashboard exists.
- [ ] Workstream C: at least 1 evolved prompt variant gets human-approved and merged.
- [ ] No regression in Phases 1-6 functionality (all existing golden tests still pass).
- [ ] No telemetry data has left the customer environment (audit via network logs).

---

## 6. What we explicitly defer past Phase 7

- **Full WASM sandboxing for MCP tools**: adds significant infra, only valuable when multi-tenant. If a customer demands it, scope separately.
- **ZKP auditability**: interesting academically, not a real buyer requirement. Defer indefinitely.
- **Federated learning across customer deployments**: data-privacy nightmare in regulated industries. Each customer trains their own model.
- **Autonomous prompt rewriting in production**: the self-evolving loop stays in shadow mode. Production prompts remain human-reviewed.

---

## 7. Files produced / modified

| File | New / Modified |
|------|----------------|
| `src/world/telemetry/*.py` | NEW |
| `src/world/predict/*.py` | NEW |
| `src/mcp/middleware/credit.py` | NEW |
| `src/evolve/*.py` | NEW |
| `src/mcp/tools/predict_regression.py` | NEW |
| `src/mcp/tools/admin_credit.py` | NEW |
| `src/graph/store.py` | MODIFIED (runtime_weight) |
| `src/simulate/risk.py` | MODIFIED (pred_prob integration) |
| `web/admin_routes.py` | MODIFIED (anomalies, proposals) |
| `config.yaml` | MODIFIED (world_model.*, credit.*) |
| `requirements.txt` | MODIFIED (xgboost or lightgbm, prometheus-client, opentelemetry-proto) |

---

*End of Phase 7. At this point Agent Hub is the trust substrate described in `STRATEGY.md`: grounded, cited, verified, simulated, and adaptive. Everything beyond is new strategy work — not more roadmap.*
