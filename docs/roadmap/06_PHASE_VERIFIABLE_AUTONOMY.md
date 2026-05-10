# Phase 6 — Verifiable Autonomy (formal verification + simulation)

> **Mode**: `verifier-engineer` (new, see `.roomodes`). Falls back to `mcp-engineer` for pure tool work.
> **Effort**: 9 weeks (weeks 16-24 in master timeline).
> **Prerequisite**: Phases 1, 2, 4 complete. Phase 5 can run in parallel.
> **Strategic context**: read [`STRATEGY.md`](STRATEGY.md) first. This phase delivers **pillars 3 and 4** (verification + simulation).

---

## 1. Why this phase is the real differentiator

After Phases 1-5, Agent Hub has:
- Grounded indexing (no hallucinations in information).
- Cited tools (no hallucinations in responses).
- A graph of the codebase.
- A changelog.
- MCP tools accessible to every AI coding agent.

That's the entry fee. Competitors will match it in 12-18 months.

Phase 6 is what makes Agent Hub irreplaceable: **the ability for an AI agent to propose a change and receive, in < 30 seconds, a mathematical proof that the change respects the codebase's invariants, along with a simulation of its runtime impact.**

This turns AI code review from "human reads diff" into "system proves safety → human reviews intent". That's the 10x unlock for regulated industries.

---

## 2. What we build

### 2.1 Neuro-symbolic verification

A pipeline that takes:
- A proposed change (patch or new file).
- A set of **policies** (YAML-declared invariants, security rules, architectural constraints).

And returns:
- `verified: True` + a proof trace, or
- `verified: False` + a counterexample (the specific input/state that breaks the policy).

Built on **Z3** (via Python bindings OR subprocess, both supported). Optionally federated with the **Chiasmus MCP server** if stable; we do not hard-depend on an external MCP server for the core path.

### 2.2 Policy DSL

Users declare invariants in YAML under `policies/*.yaml`:

```yaml
# policies/auth_required.yaml
id: auth_required_for_admin_endpoints
description: "Every endpoint matching /admin/* must have an @AuthRequired annotation"
applies_to:
  node_type: Endpoint
  selector: "path startswith '/admin/'"
invariants:
  - type: annotation_present
    name: AuthRequired
severity: error
```

Policies live alongside the code, versioned in git, reviewed like any other config.

### 2.3 Fact extractors

AST + graph → Z3 facts. Converts structural information ("this method calls X", "this class has annotation Y", "this endpoint is reachable from controller Z") into SMT formulas the solver can reason over.

### 2.4 CodeSim (call-graph simulation)

Given a proposed change and a depth parameter, trace forward through the graph + historical patterns to predict which modules, tests, and services are affected. No runtime execution; static + statistical prediction based on the World Model seeds (fully built out in Phase 7).

### 2.5 Three new MCP tools

| Tool | Input | Output |
|------|-------|--------|
| `verify_change(patch, policies?)` | Unified diff + optional policy set | `verified: bool`, `violations: [...]`, `proof_trace: ...`, `sources: [...]` |
| `simulate_change(patch, depth?)` | Unified diff + optional graph-traversal depth | `affected_modules: [...]`, `affected_tests: [...]`, `risk_score: 0-1`, `sources: [...]` |
| `check_invariants(module, policies?)` | Module ID + optional policy set | `invariants_held: [...]`, `invariants_violated: [...]`, `sources: [...]` |

All three require citations. All three refuse to operate on unverified inputs (if the graph doesn't cover the module, they abstain rather than guess).

---

## 3. Phase 6 deliverables (overview)

| ID | Deliverable | Effort |
|----|-------------|--------|
| `src/verify/` | New package | — |
| `src/verify/solver.py` | Z3 bridge | 2d |
| `src/verify/policy.py` | Policy DSL loader + validator | 2d |
| `src/verify/facts.py` | AST + graph → SMT facts | 4d |
| `src/verify/pipeline.py` | Orchestrator | 2d |
| `src/verify/policies_builtin/` | 10 built-in policies | 3d |
| `src/simulate/` | New package | — |
| `src/simulate/graph_walker.py` | Call-graph forward/backward traversal with depth limit | 2d |
| `src/simulate/risk.py` | Risk scoring (deterministic heuristic + graph metrics) | 2d |
| `src/mcp/tools/verify_change.py` | MCP tool | 1.5d |
| `src/mcp/tools/simulate_change.py` | MCP tool | 1.5d |
| `src/mcp/tools/check_invariants.py` | MCP tool | 1d |
| `tests/golden/test_verification.py` | Golden tests | 3d |
| `tests/fixtures/policies/` | 5 hand-crafted policy+code fixtures | 1d |
| `docs/policies/authoring.md` | User guide for writing policies | 1d |
| `.roo/skills/neuro-symbolic.md` | Roo skill for this phase | (already) |
| Updated `config.yaml` | `verify.*` section | — |
| Updated `requirements.txt` | Add `z3-solver` | — |

Total ~35 engineer-days ≈ 7 weeks solo. Add 2 weeks buffer for integration + regulated-industry edge cases = 9 weeks.

---

## 4. Tasks

### T-601 — Z3 bridge `src/verify/solver.py`

**Mode**: `verifier-engineer`
**Effort**: 2 days
**Depends on**: nothing (Z3 is standalone).

**CONTEXT**
A minimal wrapper over `z3-solver` (pip package) that hides Z3 types behind clean Python functions. We don't expose Z3 objects outside this module — it's an implementation detail we may later swap for Chiasmus or another SMT backend.

**FILES**

Create `src/verify/solver.py`:

```python
"""Z3 bridge. The only module in the repo that imports z3 directly.

Public API:
    solver = Solver()
    solver.declare_symbol(name, sort)     # sort: "bool" | "int" | "string" | ...
    solver.assert_fact(expr)              # expr: FactExpr
    solver.assert_policy(expr)            # typically a negation of desired invariant
    result = solver.check(timeout_ms=5000)
    # result: Verdict(status=SAT|UNSAT|UNKNOWN, model=dict|None, unsat_core=[...]|None)

Where FactExpr is a small AST we build in facts.py — NOT a Z3 expression.
"""

from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class FactExpr:
    op: str                         # "eq" | "neq" | "and" | "or" | "not" | "implies" | "var" | "const"
    args: tuple                     # nested FactExpr or primitives

@dataclass
class Verdict:
    status: Literal["SAT", "UNSAT", "UNKNOWN", "TIMEOUT", "ERROR"]
    model: dict | None              # counterexample if SAT
    unsat_core: list | None         # identifiers of clauses that caused UNSAT
    duration_ms: int
    error: str | None = None

class Solver:
    def __init__(self): ...
    def declare_symbol(self, name: str, sort: str) -> None: ...
    def assert_fact(self, expr: FactExpr, label: str | None = None) -> None: ...
    def check(self, timeout_ms: int = 5000) -> Verdict: ...
    def reset(self) -> None: ...
```

**Implementation notes**:
- Convert `FactExpr` to z3 objects at assert time.
- Catch every Z3 exception; never let one escape this module.
- Use unsat cores for explainability (Z3 supports `z3.Solver.unsat_core()` if you use `check` with labeled assertions).

**ACCEPTANCE**
- Unit tests in `tests/test_verify_solver.py`:
  - Trivial SAT: assert x==1, x==1 → SAT.
  - Trivial UNSAT: assert x==1, x==2 → UNSAT with unsat_core containing both.
  - Timeout: assert a hard problem with timeout=100ms → UNKNOWN or TIMEOUT.
  - Invalid input: malformed FactExpr → ERROR (not crash).
- No `import z3` anywhere outside this file (enforce via a grep in CI).

**ANTI-PATTERNS**
- Do NOT leak Z3 types across the module boundary.
- Do NOT build a full first-order-logic DSL; stick to the small `FactExpr` shape.
- Do NOT skip the timeout — verification must fail closed on stuck problems.

---

### T-602 — Policy DSL `src/verify/policy.py`

**Mode**: `verifier-engineer`
**Effort**: 2 days
**Depends on**: nothing.

**CONTEXT**
Policies are the user's declarative invariants. They must be:
- Human-readable (YAML).
- Reviewable in git PRs.
- Composable (policies can reference other policies).
- Versioned (breaking changes bump a schema version).

**FILES**

`src/verify/policy.py`:

```python
"""Policy DSL loader + validator.

Policy file schema (YAML):

    schema_version: 1
    id: <unique_id>                  # kebab-case
    description: <human text>
    applies_to:
      node_type: Module | Class | Method | Endpoint | Service
      selector: <filter expression>  # e.g. "name matches 'Admin.*'"
    invariants:
      - type: annotation_present
        name: AuthRequired
      - type: never_calls
        target: Method
        match: "name matches 'raw.*Sql'"
      - ...
    severity: error | warn | info

Invariant types (implemented in T-603 via fact extractors):
  - annotation_present(name)       structural
  - never_calls(match)              graph-based
  - always_called_by(match)         graph-based
  - field_type_is(field, type)     structural
  - method_visibility(visibility)  structural
  - no_cycles_in(relation)         graph-based
  - composed_of(policy_ids)        recursive (reference other policies)

API:
  loader = PolicyLoader(config)
  policies = loader.load_all()     # from policies/**/*.yaml
  for p in policies:
      p.validate()                  # static checks on the policy itself
"""

from dataclasses import dataclass
import yaml

@dataclass
class Policy:
    id: str
    description: str
    applies_to: dict
    invariants: list[dict]
    severity: str
    source_path: str

class PolicyLoader:
    def __init__(self, config): ...
    def load_all(self) -> list[Policy]: ...
    def load_one(self, path: str) -> Policy: ...
```

`src/verify/schemas/policy_schema.json`: JSON Schema for validation. Every policy file is validated against this before any reasoning happens.

**ACCEPTANCE**
- 5 valid fixture policies load successfully.
- 5 invalid fixture policies (wrong schema, bad reference, missing fields) fail with clear messages pointing to the offending file + line.
- `loader.load_all()` on the real `policies/` directory returns a sorted list.

**ANTI-PATTERNS**
- Do NOT let policies express arbitrary Python or SQL; keep it declarative. Arbitrary expression support creates audit gaps.
- Do NOT allow "any selector string"; parse selectors into a small typed AST.

---

### T-603 — Fact extractors `src/verify/facts.py`

**Mode**: `verifier-engineer`
**Effort**: 4 days
**Depends on**: T-601, T-602, Phase 2 (graph store).

**CONTEXT**
The heart of the pipeline. For each (policy, candidate node) pair, generate the SMT facts needed to verify the invariant.

**FILES**

`src/verify/facts.py`:

```python
"""Generate FactExpr assertions from the graph + AST for a given policy.

For each invariant type, there is a fact-extraction function that:
  1. Reads relevant data from the graph store + identifier index.
  2. Declares symbols to the solver.
  3. Asserts facts expressing the current state of the code.
  4. Asserts the NEGATION of the desired invariant.
If the solver returns SAT, the invariant is VIOLATED (a counterexample was found).
If UNSAT, the invariant HOLDS.

Extraction functions:
  extract_annotation_present(node, solver, graph)
  extract_never_calls(node, solver, graph, match)
  extract_always_called_by(node, solver, graph, match)
  extract_field_type_is(node, solver, graph, field, typ)
  extract_method_visibility(node, solver, graph, visibility)
  extract_no_cycles_in(node, solver, graph, relation)
  extract_composed_of(node, solver, graph, policy_ids)   # recurses

Each function returns a list of (FactExpr, label) pairs. The pipeline then
asserts them to the solver with labels, enabling unsat-core explanations.
"""
```

Each invariant type is implemented as a small, well-tested function. Start with `annotation_present` and `never_calls` (these cover ~60% of realistic policies).

**ACCEPTANCE**
- On a fixture with a known-compliant module: all invariants return UNSAT (i.e., hold).
- On a fixture with a known-violating module: the failing invariant returns SAT with a non-empty model pointing to the violating entity.
- Extraction time for a 10k-node graph: < 1 second per policy per candidate node.

**ANTI-PATTERNS**
- Do NOT call the LLM inside fact extractors. Structural reasoning only.
- Do NOT generate facts for irrelevant nodes (waste + false-positive risk). Apply the policy's selector first.

---

### T-604 — Orchestrator `src/verify/pipeline.py`

**Mode**: `verifier-engineer`
**Effort**: 2 days

**CONTEXT**
Ties solver + policies + facts together. Exposes a clean function the MCP tool can call.

**FILES**

`src/verify/pipeline.py`:

```python
"""Verification orchestrator.

verify_change(patch_text: str, policies: list[Policy], graph_store, config) -> VerdictReport

Steps:
  1. Apply the patch virtually (do NOT modify workspace). Produce a post-patch snapshot
     of affected files in-memory.
  2. Re-run AST extraction on affected files (Phase 2 extractor_ast).
  3. Merge the snapshot graph with the existing graph (overlay).
  4. For each policy:
       a. Find candidate nodes (applies_to.selector).
       b. For each candidate: extract facts + check via solver.
       c. Record verdict (holds / violates + evidence).
  5. Assemble VerdictReport: { overall_verdict, per_policy_results, citations }.

VerdictReport structure:
    {
      "overall": "pass" | "fail" | "unknown",
      "policies_checked": int,
      "violations": [
        { "policy_id": ..., "severity": ...,
          "candidate_node": ..., "reason": ...,
          "counterexample": ..., "sources": [...] }
      ],
      "proof_traces": [
        { "policy_id": ..., "unsat_core": [...], "duration_ms": ... }
      ],
      "sources": [...]   # aggregated for citation middleware
    }
"""
```

**ACCEPTANCE**
- Runs end-to-end on a patch + 3 policies in < 10 seconds on the user's workspace.
- Violations include a counterexample field that a human can understand ("method `foo` at Foo.java:42 calls `rawSql(...)` which violates `never_calls_raw_sql`").
- No-violation case returns empty `violations` + populated `proof_traces`.

**ANTI-PATTERNS**
- Do NOT actually apply the patch to the filesystem. Always in-memory.
- Do NOT skip re-extracting AST on changed files; stale facts → wrong verdicts.

---

### T-605 — MCP tool `verify_change`

**Mode**: `mcp-engineer` (with `verifier-engineer` consulting)
**Effort**: 1.5 days
**Depends on**: T-604, Phase 4 MCP framework.

**CONTEXT**
Exposes `pipeline.verify_change()` as an MCP tool. Standard contract: `requires_citations = True`.

**FILES**

`src/mcp/tools/verify_change.py`:

```python
class VerifyChangeTool(BaseTool):
    name = "verify_change"
    description = "Check a proposed change against formal policies. Returns verdict + violations + proofs."
    input_schema = {
        "type": "object",
        "properties": {
            "patch": {"type": "string", "description": "Unified diff", "maxLength": 1_000_000},
            "policies": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Policy IDs to enforce. Empty = all applicable policies."
            },
            "timeout_ms": {"type": "integer", "minimum": 100, "maximum": 60_000, "default": 10_000}
        },
        "required": ["patch"],
        "additionalProperties": False
    }
    output_schema = {
        "type": "object",
        "properties": {
            "overall": {"enum": ["pass", "fail", "unknown"]},
            "violations": {"type": "array", "items": {...}},
            "proof_traces": {"type": "array", "items": {...}},
            "sources": {"type": "array", "items": {...}}
        },
        "required": ["overall", "violations", "sources"]
    }
    requires_citations = True
    auth_required = False
    rate_limit_per_minute = 20   # expensive
```

**ACCEPTANCE**
- Golden test: known-good patch → `overall: "pass"`.
- Golden test: known-bad patch (violates `auth_required_for_admin_endpoints`) → `overall: "fail"` with the expected violation.
- Citation contract: every violation has a `sources` entry pointing to the offending code.
- Timeout handling: if the solver times out, `overall: "unknown"` (NOT `"pass"`).

**ANTI-PATTERNS**
- Do NOT default to `"pass"` on errors or timeouts. Fail closed for the caller to decide.

---

### T-606 — CodeSim MCP tool `simulate_change`

**Mode**: `mcp-engineer`
**Effort**: 2 days
**Depends on**: Phase 2 (graph), Phase 3 (temporal optional for risk scoring).

**CONTEXT**
Static impact analysis: given a patch, what modules/services/tests does it affect, and how risky is it? No runtime execution; pure graph traversal + heuristics.

**FILES**

`src/simulate/graph_walker.py`:

```python
"""Forward and backward traversal of the call graph with depth limits.

walk_forward(graph, changed_files, depth) -> set[node_id]
    # what might be affected if these files change
walk_backward(graph, changed_files, depth) -> set[node_id]
    # what produces or depends on these files
affected_tests(graph, changed_nodes) -> list[test_id]
    # tests with a path to any changed node
"""
```

`src/simulate/risk.py`:

```python
"""Deterministic risk scoring. No LLM.

risk_score(
    changed_files: list[str],
    affected_modules: set[str],
    affected_tests: set[str],
    graph_stats: dict,         # hub-ness metrics
    temporal_signals: dict,    # from Phase 3 enricher, optional
) -> float  # 0.0..1.0

Components (each weighted):
  - file_count      (log-scaled)
  - fan_out         (edges leaving changed nodes)
  - hub_touch       (does the change involve a hub module?)
  - test_coverage   (ratio of affected code with test paths)
  - historical_risk (from temporal enricher: commits to these files had fix follow-ups? Phase 3+)
"""
```

`src/mcp/tools/simulate_change.py`: the MCP tool, wiring the above.

**ACCEPTANCE**
- Patch touching a hub module → high risk score.
- Patch touching a leaf method → low risk score.
- Returned `affected_tests` are actually in the graph (verified by path query).
- Latency < 3 seconds on user's workspace.

**ANTI-PATTERNS**
- Do NOT call the LLM for risk scoring. Deterministic only; humans need to trust and reproduce the score.

---

### T-607 — `check_invariants` MCP tool

**Mode**: `mcp-engineer`
**Effort**: 1 day

**CONTEXT**
Second MCP tool over the verification pipeline. Unlike `verify_change`, this checks the *current* state of a module against all applicable policies. Useful for "is this subsystem already compliant?" queries.

**FILES**

`src/mcp/tools/check_invariants.py`: straightforward — call `pipeline.verify_module(module_id, policies)` with an empty patch.

**ACCEPTANCE**
- Reports which policies apply to the queried module and which hold/violate.
- Completes in < 5 seconds for a typical module.

---

### T-608 — 10 built-in policies + authoring guide

**Mode**: `verifier-engineer`
**Effort**: 3 days

**CONTEXT**
Ship with policies that cover common concerns, so users get value on day 1. Plus a guide for writing custom policies.

**FILES**

`src/verify/policies_builtin/`:

1. `admin_endpoints_require_auth.yaml`
2. `no_raw_sql_in_service_layer.yaml`
3. `controllers_do_not_call_each_other.yaml`
4. `no_static_mutable_state.yaml` (language-specific Java / Python variants)
5. `deprecation_annotations_on_public_api.yaml`
6. `no_hardcoded_secrets.yaml` (regex-backed, not SMT)
7. `async_methods_return_future.yaml` (Java)
8. `config_constants_use_frozen_types.yaml` (Python)
9. `entity_fields_have_validation.yaml`
10. `endpoints_have_rate_limit.yaml`

`docs/policies/authoring.md`: guide walking a user through writing a custom policy. Covers selector syntax, invariant types, debugging failed checks, review workflow.

**ACCEPTANCE**
- Each built-in policy passes against a known-compliant fixture.
- Each built-in policy fails (with correct reason) against a hand-crafted violating fixture.
- Authoring guide walks through a non-trivial example end-to-end (write policy → run → see result → iterate).

**ANTI-PATTERNS**
- Do NOT ship policies that produce false positives on real idiomatic code. Tune on the user's workspace before marking done.

---

### T-609 — Auto-policy suggestions (shadow mode)

**Mode**: `verifier-engineer`
**Effort**: 3 days
**Depends on**: T-608.

**CONTEXT**
Advanced feature: the system analyzes the codebase + temporal store and *suggests* policies the user might want. Runs in shadow mode — suggestions are written to `context/policy_suggestions.md`, never automatically enforced.

Example suggestions:
- "All 38 `*Repository` classes have `@Repository` annotation. 0 violations in last 6 months. Consider promoting to enforced policy."
- "`UserController.deleteUser` was touched by 3 bug-fix commits in last 3 months (above 95th percentile). Consider adding invariant tests."

**FILES**

`src/verify/suggest.py`: scans the graph + temporal store for patterns that *look like* invariants (high consistency + meaningful signal). Emits markdown suggestions.

**ACCEPTANCE**
- Produces at least 3 non-trivial suggestions on user's workspace.
- Each suggestion includes: rationale, evidence (commit refs or node counts), proposed YAML policy text, severity.

**ANTI-PATTERNS**
- Do NOT auto-enforce suggestions. Ever. Shadow mode only until user promotes them.

---

## 5. Phase 6 success gate

Before shipping v2.0:

- [ ] All 10 built-in policies ship with golden tests.
- [ ] `verify_change` on a known-bad patch correctly identifies the violation with counterexample.
- [ ] `verify_change` latency < 30s P95 on user's workspace.
- [ ] `simulate_change` returns affected modules that match human intuition on 5 sample patches.
- [ ] `check_invariants` can report on any module in the user's workspace.
- [ ] 0 false positives (policy violations on known-compliant code) on the user's workspace during a 1-week soak test.
- [ ] Customer-authored policies work (user writes one custom policy following the guide, it runs).
- [ ] Authoring guide is complete.

---

## 6. Files produced / modified

| File | New / Modified |
|------|----------------|
| `src/verify/solver.py` | NEW |
| `src/verify/policy.py` | NEW |
| `src/verify/facts.py` | NEW |
| `src/verify/pipeline.py` | NEW |
| `src/verify/suggest.py` | NEW |
| `src/verify/schemas/policy_schema.json` | NEW |
| `src/verify/policies_builtin/*.yaml` | NEW (10 files) |
| `src/simulate/graph_walker.py` | NEW |
| `src/simulate/risk.py` | NEW |
| `src/mcp/tools/verify_change.py` | NEW |
| `src/mcp/tools/simulate_change.py` | NEW |
| `src/mcp/tools/check_invariants.py` | NEW |
| `tests/golden/test_verification.py` | NEW |
| `tests/fixtures/policies/` | NEW |
| `docs/policies/authoring.md` | NEW |
| `config.yaml` | MODIFIED (verify.* section) |
| `requirements.txt` | MODIFIED (z3-solver) |
| `.roo/skills/neuro-symbolic.md` | NEW |

---

*End of Phase 6. At this point Agent Hub ships pillars 1-3 (grounding, citations, verification) + a deterministic version of pillar 4. The full learned-world-model version of pillar 4 is Phase 7.*
