# Agent Hub — Strategy (v2)

> **The North Star.** Read this before any roadmap document. If a task in the roadmap contradicts this strategy, the strategy wins.

---

## 1. The thesis

AI coding agents are getting faster than human review. Cline, Roo Code, Claude Code, Cursor can now produce hundreds of lines of plausible code per minute. The scarce resource in software engineering is no longer generation — it's **trust**.

Today, that trust comes from a line-by-line human review. It does not scale. Engineering orgs hit a ceiling where the reviewer becomes the bottleneck, and AI productivity is thrown away waiting at the PR gate.

**Agent Hub's bet**: the next decade of software engineering will be won by whoever shifts the trust model from *review* to *proof*. The organizations that can say "this change is formally verified against our invariants, its call-graph impact is bounded, its telemetry predictions pass the regression threshold, and every claim it makes is cited to source" will ship 10x faster than those still reviewing diffs by hand.

Agent Hub is the **trust substrate** for that world.

---

## 2. The four trust pillars

Agent Hub's product is the convergence of four layers of trust. Each pillar is necessary; together they are sufficient.

| # | Pillar | What it delivers | Phase |
|---|--------|------------------|-------|
| 1 | **Grounding** | Every statement the system makes is anchored in source. No hallucinated class names, no invented methods. | 1 |
| 2 | **Citations** | Every MCP tool response includes verifiable source ranges. An external consumer can re-check every claim. | 4 |
| 3 | **Verification** | Proposed changes are checked against formal policies (security, invariants, architectural rules) using an SMT solver. Violations are caught before merge. | 6 |
| 4 | **Simulation** | Proposed changes are traced through the call graph + production telemetry to predict behavioral impact and regression risk. | 6 + 7 |

Pillars 1 and 2 are the entry fee. Pillars 3 and 4 are what make Agent Hub **world-changing** rather than merely useful.

---

## 3. Why now

Three technologies matured in 2025-2026 that make this feasible:

1. **MCP (Model Context Protocol)** — standard for agent-to-tool plumbing. We stand on this, we don't reinvent it.
2. **Tree-sitter universal parsers** — structural accuracy on arbitrary languages without JVM/per-language toolchains.
3. **SMT solvers shipped as MCP servers** (Z3, Chiasmus) — formal verification accessible to LLMs via standard tool-call interface.

Plus: vLLM + Mistral-class open models mean we can run the whole stack self-hosted, which is a hard requirement for the target buyers (regulated industries, defense, finance, healthcare). This is not a SaaS story.

---

## 4. Who this is for

Three personas, in priority order:

### 4.1 The platform team at a regulated-industry company (primary)
They own a 1-10M LOC codebase that *cannot* hallucinate. Banks, insurers, aerospace, medtech, industrial simulation. They will not use cloud AI tools for compliance reasons. They want AI productivity without the risk. **Agent Hub sells to them because verification + self-hosted is the only viable combo.**

### 4.2 The engineering lead at a fast-growing startup (secondary)
They want their AI coding agents to stop hallucinating imports, breaking modules they've never seen, and drowning reviewers in churn. Grounding + citations is enough for them; verification is a nice-to-have. **Agent Hub sells to them because Phase 1-4 ships quickly and has measurable quality wins.**

### 4.3 The research lab (tertiary)
Universities, national labs, corporate research divisions. They want the world model + simulation layer to study how code evolves. Low revenue per user but high prestige + feature pressure. **Agent Hub tolerates them because they drive Phase 7 innovation.**

---

## 5. Business goals (horizon 18 months)

1. **H1 2026**: Ship v1.0 (Phases 0-5). Target: 50 self-hosted installations across pilot customers. Definition of done: hallucination rate < 2% across all MCP tool responses, measured on each deployment's own workspace.

2. **H2 2026**: Ship v2.0 (Phase 6 — Verifiable Autonomy). Target: 5 regulated-industry deployments running with formal verification on critical paths. Definition of done: each deployment has at least 10 project-specific invariants enforced by the verifier, zero false-positive merges of policy-violating changes over a 30-day window.

3. **H1 2027**: Ship v3.0 (Phase 7 — Adaptive Intelligence). Target: 2 deployments running with world-model-driven regression prediction. Definition of done: regression prediction AUC > 0.8 on each deployment's historical incident data.

4. **Parallel**: open-source release under Apache 2.0 (v1.0 onward). Build the MCP ecosystem around us — every new coding-agent tool that integrates MCP should find Agent Hub when they search "grounded code knowledge".

---

## 6. Priorities (what we don't do)

The ambition is large. Discipline comes from what we **refuse**.

| We do NOT build | Because |
|-----------------|---------|
| A code editor, IDE plugin, or diff applier | Cline / Roo / Cursor / Claude Code own this. We feed them. |
| A chat UI as the primary product | Open WebUI owns this. We plug into it for the 20% of users who want it. |
| A cloud-hosted SaaS version | Regulated buyers won't use it. Self-hosted is a feature, not a limitation. |
| An agent marketplace / orchestration platform for business workflows | Out of scope. Code is the focus. |
| A general-purpose LLM gateway / routing layer | Users pick their own vLLM. We ship against any OpenAI-compatible endpoint. |
| Zero-knowledge proof infrastructure | Cryptographic auditability is overkill for single-tenant self-hosted. Return to it if a customer explicitly demands it (haven't seen it). |
| A UI for non-technical users to "talk to their code" | Adjacent product. If built, separate repo (see DECIDE-1 for precedent). |

The Dossier stratégique cited all of these as possible directions. We say no, because saying yes dilutes Phases 6-7 and loses the window.

---

## 7. The roadmap at a glance (v2)

```
Phase 0 — Cleanup                            [week 1]
Phase 1 — Anti-Hallucination (Grounding)     [weeks 2-4]    [BLOCKING everything]
Phase 2 — GraphRAG (AST + graph)             [weeks 5-7]    [parallel w/ 3, 4]
Phase 3 — Changelog Fix                      [weeks 5-6]    [parallel w/ 2, 4]
Phase 4 — MCP Framework + 23 tools           [weeks 5-11]   [depends on 1]
Phase 5 — Pipelines + Wiki + Multi-repo      [weeks 12-15]  [depends on 4]

v1.0 SHIPS HERE (week 15)
                        ↓
Phase 6 — Verifiable Autonomy                [weeks 16-24]  [depends on 2, 4]
  ├─ neuro-symbolic verification (Z3)
  ├─ policy DSL + fact extractors
  ├─ CodeSim (call-graph simulation)
  ├─ new MCP tools: verify_change, simulate_change, check_invariants

v2.0 SHIPS HERE (week 24)
                        ↓
Phase 7 — Adaptive Intelligence              [weeks 25-40+] [depends on 6]
  ├─ telemetry-enriched world model
  ├─ regression prediction
  ├─ capability registry + credit scoring (immune system, lite)
  ├─ shadow-mode prompt self-evolution

v3.0 SHIPS HERE (week 40+)
```

Phases 6 and 7 are the revolutionary part. They are **gated by Phase 1's hallucination rate**: if Phase 1 doesn't ship < 2% hallucinations, everything downstream is built on sand and we refuse to proceed.

---

## 8. The new strategic decisions

Two additions to the existing 8 decisions (cf `docs/decisions/`):

- **DECIDE-9**: Reposition the product from "MCP server for coding agents" to "**trust substrate for autonomous code**". Marketing, README, sales conversations are rewritten around the four trust pillars.
- **DECIDE-10**: Adopt neuro-symbolic verification (Z3 via subprocess OR the Chiasmus MCP server if stable) as a first-class capability in Phase 6. Invest in the fact-extractor infrastructure even though it requires per-language parsers.

Full ADRs in `docs/decisions/0009-trust-substrate.md` and `docs/decisions/0010-neuro-symbolic.md`.

---

## 9. How this changes daily work

For the coding agent (Roo + Nemotron):

- **Phases 0-5 execute essentially unchanged.** The strategy sharpens the *why* but not the *what* of tasks T-001 through T-540.
- **Phases 6-7 are new documents** (`06_PHASE_VERIFIABLE_AUTONOMY.md`, `07_PHASE_ADAPTIVE_INTELLIGENCE.md`). Tasks T-601+ and T-701+ live there.
- **One new Roo mode**: `verifier-engineer` (for Phase 6's formal-methods work). Added to `.roomodes`.
- **One new Roo skill**: `.roo/skills/neuro-symbolic.md`.

For the human (you):

- Read this document once. Re-read §7 (roadmap) periodically to check where you are.
- When a stakeholder asks "what is Agent Hub?", the answer comes from §1-2 of this doc, not from the README. (Update README to match, T-005b.)
- When a feature request arrives, check §6. If the request is in "we do NOT build", say no. The ambition requires discipline.

---

## 10. The one-line version

> **Agent Hub makes AI-written code trustworthy enough to ship, at the pace AI writes it.**

Everything else follows from that sentence.
