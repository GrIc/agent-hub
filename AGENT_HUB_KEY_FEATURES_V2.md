# Agent Hub — Key Features (v2, Trust Substrate pitch)

> The v1 feature list was "cool things we can do". The v2 list is "**why you cannot ship AI-written code without us**".

---

## 1. The one-line positioning

**Agent Hub makes AI-written code trustworthy enough to ship, at the pace AI writes it.**

Not a "better RAG". Not an "agent platform". The **trust substrate** between AI coding agents and production codebases.

---

## 2. The four pillars (what we actually sell)

### Pillar 1 — **Grounded Knowledge**
Every fact Agent Hub states about your codebase is anchored in source. No hallucinated class names, no invented methods, no imaginary modules. Hallucination rate **under 2%**, measured and published per install.

### Pillar 2 — **Cited Responses**
Every MCP tool response carries verifiable `sources: [{path, line_start, line_end}]`. Your AI coding agent can re-check every claim. Your reviewers can audit every reference. Your compliance officer can certify every decision chain.

### Pillar 3 — **Formal Verification** ⭐ *The unlock for regulated industries*
Propose a change → Agent Hub proves (via SMT solver) whether it respects your policies. Auth required on admin endpoints? No raw SQL in the service layer? Rate limits on public APIs? Declare the policy once, enforce it forever. Violations come with **counterexamples**, not warnings.

### Pillar 4 — **Behavioral Simulation**
Before a change merges, Agent Hub walks your call graph and production telemetry to predict which services, tests, and users will be affected. Static impact analysis (v2.0) → learned regression prediction (v3.0). Your reviewer sees the blast radius, not just the diff.

---

## 3. What this unlocks

### For the regulated-industry CTO
- **10x faster shipping on critical codebases** because policy compliance is proven, not re-reviewed.
- **Audit trail by default**: every AI-made change has a verified provenance.
- **On-prem only**: zero cloud dependency, compatible with classified / HIPAA / PCI / ITAR environments.

### For the engineering lead at a startup
- **AI coding agents stop breaking things** because every answer they get is grounded and cited.
- **Onboarding time cut in half**: the living wiki + architecture blueprint tool means new engineers have a senior-level mental model on day one.
- **Changelog you actually read**: enriched per-commit summaries with risk scores, delivered to Slack/email/Markdown.

### For the AI coding agent itself
- **A `list_tools` of 30+ tools** spanning code search, graph reasoning, history intelligence, pattern discovery, formal verification, and impact simulation.
- **Composable pipelines** to chain tools without writing Python.
- **Standard MCP protocol** — works with Cline, Roo Code, Claude Code, Cursor, Continue.dev, and anything else that speaks MCP.

---

## 4. The feature list (sell sheet version)

### Indexing & knowledge

- **Grounded indexing** — hallucination rate < 2%, enforced via validation + reject-retry-abstain
- **Tree-sitter AST graph** — structural triplets with zero LLM calls for structure
- **LLM-enriched semantic layer** — class/service descriptions that stay grounded
- **Hierarchical synthesis (L0-L3)** with traceability links between levels
- **Incremental everything** — reindex only what changed, every step

### MCP tools (29 tools in v1.0, 32 in v2.0)

- **Semantic code search** with intent + filters
- **Architecture blueprint generator** (flagship) — for a feature description, returns similar code, recommended modules, insertion points, risks
- **Call graph tools** — get_callers, get_callees, shortest_path, find_hub_modules
- **Impact preview** — static blast-radius analysis
- **Temporal tools** — recent changes, why_does_this_exist, what_changed_here, blame+
- **Pattern & convention discovery** — list_patterns, check_conventions
- **Auto-generated living wiki** — get_wiki_page, wiki_search
- **Changelog delivery** — file, Slack, email out of the box

### Verification (v2.0 — the regulated-industry unlock)

- **`verify_change`** — take a patch + policies, return proof or counterexample
- **`simulate_change`** — affected modules, tests, services with risk score
- **`check_invariants`** — inspect a module's current compliance
- **10 built-in policies** shipping on day 1 (auth requirements, SQL hygiene, deprecation patterns, etc.)
- **Policy DSL** — YAML, reviewable in git, composable
- **Zero false positives** guarantee on known-compliant code (or we fix the policy)

### Adaptive intelligence (v3.0 — horizon 2)

- **Regression predictor** — P(incident | patch) from telemetry-enriched graph, self-trained on your history
- **Tool credit scoring** — MCP tools earn/lose trust based on behavior; quarantine bad actors automatically
- **Shadow-mode prompt evolution** — the system proposes better prompts; humans approve

### Operations

- **One-command Docker setup**
- **Opt-in telemetry** only — zero outbound traffic by default
- **Multi-repo federation** — query across workspaces, cross-repo call graphs
- **Auto-generated MCP tool documentation**
- **Admin dashboards** for quality, graph, changelog, anomalies, proposals
- **Custom pipelines** authored in YAML

---

## 5. Competitive matrix (v2)

| Feature | Agent Hub v2 | Copilot Enterprise | Cursor Team | Generic RAG | Confluence |
|---------|---|---|---|---|---|
| Self-hosted / on-prem | ✅ | ✅ Enterprise only | ❌ | ✅ if DIY | ✅ |
| Grounding with < 2% hallucination | ✅ measured | ❌ | ❌ | ❌ | N/A |
| Citations on every response | ✅ enforced | Partial | Partial | Manual | ❌ |
| Call graph / impact preview | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Formal verification of policies** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Counterexample-based violations** | ✅ | ❌ | ❌ | ❌ | ❌ |
| Code convention discovery | ✅ | ❌ | ❌ | ❌ | Manual |
| Auto-generated wiki | ✅ | ❌ | ❌ | ❌ | Manual |
| Enriched changelog | ✅ | ❌ | Partial | ❌ | Manual |
| Pipeline / workflow composition | ✅ YAML | ❌ | ❌ | ❌ | ❌ |
| Regression prediction | v3.0 | ❌ | ❌ | ❌ | ❌ |
| Works via standard MCP | ✅ | ❌ (locked) | ❌ (locked) | If DIY | ❌ |

The **two lines that matter** are the verification ones. Nobody else has them. This is the moat.

---

## 6. Proof points (measured, not claimed)

Every deployment reports these metrics to the user:

- **Hallucination rate**: < 2% (target), validated on codex docs + synthesis + MCP responses.
- **Citation validity**: 100% of cited ranges exist on disk (enforced by middleware).
- **Verification coverage**: % of changed files passed through verify_change in the last 30 days.
- **False-positive rate**: % of policy violations later dismissed as "not a real problem".
- **Regression prediction AUC** (v3.0): on held-out history.

These aren't marketing numbers. They're generated by `/admin/quality` and `/admin/verification` dashboards. If the numbers look bad, the tool isn't ready. We ship honesty.

---

## 7. Why now — the window

- **2025-2026**: MCP protocol stabilized; tree-sitter parsers reached production quality; Z3 became LLM-callable via MCP servers.
- **2026**: AI coding agents cross the productivity gap for real engineering work (multi-file changes, refactors, new features from requirements).
- **Right now**: reviewers are the bottleneck. The market is desperate for a trust substrate that doesn't require re-reading every AI diff.

First-mover with the verification pillar + the self-hosted posture + MCP openness = category definition.

---

## 8. The three ways customers hear about us

1. **From their AI coding agent**. Cline/Roo/Cursor recommends connecting to Agent Hub for better grounding. Ecosystem play.
2. **From their compliance team**. "AI is writing code, we need audit + invariant enforcement." We're the only answer that's self-hosted.
3. **From their platform team**. "Copilot works but our AI code quality is a mess." We fix the mess via Phases 1-4, then we expand into 5-7.

Each channel speaks to a different pillar. One product, three markets.

---

## 9. The pitch (30-second version)

> "Your AI coding agents write code faster than you can review it. Today you have two options: slow them down, or trust them blindly. Agent Hub is option three: verify their work mathematically against your own policies, cite every claim they make, simulate every change before it merges. Self-hosted. Open protocol. Regulated-industry ready. You stop reviewing diffs and start reviewing intent."

---

## 10. The pitch (10-second version)

> **"We make AI-written code trustworthy enough to ship, at the pace AI writes it."**

That's the whole company.

---

*For the full strategy, see `docs/roadmap/STRATEGY.md`.
For the execution plan, see `docs/roadmap/00_MASTER_ROADMAP.md`.*
