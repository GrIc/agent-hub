# Skill: Neuro-Symbolic Verification

> Loaded by: `verifier-engineer`.
> Purpose: concrete patterns for integrating Z3 / SMT solvers with AST-derived facts to verify policies over a codebase.
> **Prerequisite reading**: `.roo/skills/grounding.md` and `.roo/skills/ast-extraction.md`.

---

## 1. The mental model

Verification = **"can the current code (plus a proposed patch) violate this policy?"**

Translated to SMT:
1. Encode the **current state** of the code as facts (structural, graph-based).
2. Encode the **policy** as the negation of the desired invariant.
3. Ask the solver: is there a satisfying assignment?
   - **UNSAT** → the negation is impossible → the invariant holds. ✓
   - **SAT** → a counterexample exists → the invariant is violated. The model points at the offending entity. ✗
   - **UNKNOWN / TIMEOUT** → we don't know. Always return `"unknown"` to the caller. **Never fall back to "pass".**

This flips the usual programmer intuition: you assert facts + you assert the *bad* state, and UNSAT means "the bad state is unreachable, we're safe".

---

## 2. Patterns for fact extraction

### 2.1 Translate structural questions into boolean predicates

| Natural-language claim | SMT encoding |
|------------------------|--------------|
| "Method X has annotation Y" | `HasAnnotation(X, Y) : Bool` |
| "Class A extends Class B" | `Extends(A, B) : Bool` |
| "Method M calls method N" | `Calls(M, N) : Bool` |
| "Endpoint E has path P" | `EndpointPath(E, "/admin/x") : String` |

Symbols are **per-candidate** (not per-codebase). For each policy invocation, declare only the symbols relevant to the candidate node and its neighbors. Global quantification is expensive and brittle.

### 2.2 Translate graph reachability

"Method M is called by some Controller" → use a recursive fact: `ReachableFrom(Controller, M) = Calls(Controller, M) OR EXISTS N. Calls(Controller, N) AND ReachableFrom(N, M)`.

Z3 handles bounded recursion via the `Fixedpoint` tactic, but for Phase 6 we **precompute reachability in the graph store** (Python walks + cache) and assert the result as boolean facts. This is simpler, faster, and easier to audit. Upgrade to Z3's native Datalog later only if needed.

### 2.3 Keep facts local to the query

A common mistake: dump the whole graph into the solver. That produces a formula with millions of clauses and UNKNOWN responses.

**Correct pattern**: for each (policy, candidate) pair:
1. Identify relevant entities via graph traversal (2-hop neighborhood by default).
2. Extract facts only for those.
3. Assert only what the policy references.

---

## 3. The assertion structure

Every policy check looks like this:

```python
def check_never_calls(policy, candidate, graph, solver):
    # 1. declare symbols
    solver.declare_symbol(f"calls_{candidate.id}_violates", "bool")

    # 2. assert facts (the present state)
    for callee in graph.get_callees(candidate.id, depth=2):
        if matches_selector(callee, policy.match):
            solver.assert_fact(
                FactExpr("var", (f"calls_{candidate.id}_violates",)),
                label=f"witness:{candidate.id}->{callee.id}"
            )
            break
    # note: the loop adds at most one witness. If none, no fact asserted.

    # 3. assert the negation of the desired invariant
    # desired: calls_X_violates == FALSE
    # we assert: calls_X_violates == TRUE
    solver.assert_fact(
        FactExpr("eq", (FactExpr("var", ("calls_{candidate.id}_violates",)), True)),
        label="desired_violation"
    )

    # 4. solve
    verdict = solver.check(timeout_ms=policy.timeout_ms)
    return verdict
```

If the solver is SAT, the unsat-core label `witness:...` tells us exactly which callee violates the rule.

---

## 4. Labeling for explainability

Always label assertions:

```python
solver.assert_fact(expr, label="my_specific_label")
```

When SAT, the model maps labels to values. Your counterexample generator reads these labels and renders a human-readable explanation:

> "Policy `no_raw_sql_in_service` violated: `UserService.getUserByName` calls `rawSql("SELECT ...")` at UserService.java:142. Counterexample: callers={UserService.getUserByName}, callees={rawSql}."

Labels without context are useless. Use structured labels: `witness:<type>:<id>:<reason>`.

---

## 5. Timeout discipline

Solvers get stuck on hard problems. Configure:

```yaml
verify:
  solver_timeout_ms_per_check: 5000     # per policy per candidate
  pipeline_total_timeout_s: 30          # hard cap for the whole verify_change call
  fall_through_on_timeout: "unknown"    # NEVER "pass"
```

Always treat a timeout as information, not an error:
- Log the policy and candidate that timed out.
- Return `"unknown"` in the verdict report.
- The caller (MCP tool) reports `overall: "unknown"` if any policy returned unknown and no policy returned fail.

Never auto-retry on timeout without tightening the fact set. A retry with the same inputs will time out again.

---

## 6. Incremental verification

On large workspaces, we want to re-check only what changed. Patterns:

- **File-level incrementality**: if the patch touches only `src/foo/Bar.java`, only re-check policies whose `applies_to.selector` could match entities in that file.
- **Selector caching**: precompute `policy_id → set[candidate_node_id]` on first run, invalidate per file change.
- **Fact caching**: the set of facts for an unchanged candidate is reusable across policies; cache by `(candidate_id, graph_revision)`.

Target: re-verification of a 1-file patch on 10 policies in < 5 seconds.

---

## 7. Counterexample rendering

When SAT, translate the Z3 model into a human message. The pipeline emits:

```json
{
  "policy_id": "no_raw_sql_in_service",
  "severity": "error",
  "candidate_node": "Method:src/user/UserService.java:142:getUserByName",
  "reason": "Calls forbidden target 'rawSql' from service layer.",
  "counterexample": {
    "path": ["UserService.getUserByName", "DbHelper.rawSql"],
    "evidence_line": 142
  },
  "sources": [
    {"path": "src/user/UserService.java", "line_start": 140, "line_end": 160}
  ]
}
```

**The `sources` field is mandatory**. Without it, the MCP citation middleware rejects the response.

---

## 8. Policy author ergonomics

A good policy:
- Has a meaningful `id` (kebab-case, 3-5 words).
- States the intent in `description` (1 sentence, past/present tense).
- Uses the narrowest selector that still covers all cases.
- Picks `severity` deliberately: `error` blocks merge, `warn` surfaces in review, `info` logs only.

Bad policies produce **false positives** on idiomatic code. Before declaring a policy done, run it against the full workspace and verify zero false positives. If there are, either:
- Tighten the selector, or
- Add the idiomatic pattern to an allowlist within the policy.

---

## 9. What the verifier CANNOT do (set expectations)

The verifier handles structural + graph-based invariants. It does **not**:

- Verify runtime behavior (that's Phase 7's world model).
- Verify arbitrary semantic intent ("this code does what it says") — LLMs or humans do that.
- Prove absence of bugs in general — only violation of declared policies.
- Replace tests — use both.

If a policy is hard to express in the DSL, it's probably outside our scope. Don't stretch.

---

## 10. Anti-patterns

| Smell | Fix |
|-------|-----|
| Dumping the whole graph into the solver | Extract a local neighborhood per candidate. |
| Returning `"pass"` on solver timeout | Return `"unknown"`. Fail closed. |
| Asserting facts without labels | Label everything. You'll need them for counterexamples. |
| Using Z3 for arithmetic on real-world quantities (currency, etc.) | Out of scope. Keep it boolean + bounded integer where possible. |
| Shipping a policy that produces false positives | Fix the selector or add an allowlist. False positives destroy trust. |
| Hard-coding Z3 expressions in policy files | Policies are YAML. Z3 lives in Python. Keep the separation. |
| Calling an LLM inside the verifier | No. The whole point is determinism. LLM can help AUTHOR policies (Phase 6 T-609), never EXECUTE them. |

---

## 11. Testing

Every policy ships two fixtures:

- `policies_builtin/<policy>.compliant.java` (or equivalent) — known-good file. Verifier must return UNSAT.
- `policies_builtin/<policy>.violating.java` — known-bad file. Verifier must return SAT with the expected counterexample.

Golden tests in `tests/golden/test_verification.py` run all policy+fixture pairs and compare against snapshots.

If a golden test changes, the author must justify it in the PR description ("why is this policy now allowing code that previously failed?"). Verification changes are load-bearing; they deserve scrutiny.

---

*End of skill.*
