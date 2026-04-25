# 0011 — Language-agnostic architecture (via declarative tree-sitter queries)

## Context

Phase 1 shipped with a validator and extractor that hard-coded Java and Python heuristics. T-FIX-001 made it worse by adding ~80 Jakarta-EE terms, English stopwords, and Java-specific annotation parsing to the validator.

This works for the pilot CATIA workspace but contradicts the product positioning ("trust substrate for any codebase"). A Rust or Kotlin customer would need equivalent patching. That's unacceptable.

The issue is not Phase 1's validator per se — it's a **temporary pragma to keep the indexer running** until Phase 2 ships the real world model. The issue is that Phase 2 v1 (as originally spec'd) would repeat the mistake at larger scale: per-language Python branches in the graph extractor, per-language noise filters, per-language prompt templates.

## Options considered

**A. Continue the v1 approach.** Per-language Python extractors, per-language prompt templates. Pragmatic, ships fastest, but violates the product's generic positioning and creates unsustainable maintenance debt (every new customer language = new Python module).

**B. Declarative queries (tree-sitter `.scm` files).** Each language gets ~30-50 lines of `.scm`; the Python extractor is uniform. Scales to ~160 languages via existing tree-sitter grammars. Industry-standard (Semgrep, Sourcegraph, GitHub code navigation all use this pattern).

**C. Full LSP integration.** Use Language Server Protocol instead of tree-sitter. More accurate (real type resolution) but requires a running LSP server per language — heavy infra, hard to self-host across 20+ languages.

## Decision

**B.** Phase 2 v2 enforces that all language-specific logic lives in `queries/<lang>.scm` files. The Python code in `src/graph/` is language-agnostic. Adding a new language = one `.scm` file + 3 lines in `parsers.py` + config entry. Zero other Python changes.

An automated test (`tests/test_graph_language_parity.py`) enforces the rule at CI time.

## Consequences

- Phase 2 timeline is the same (~3 weeks) but with a different structure.
- The Phase 1 validator's language-specific pragma is scoped and temporary: once Phase 2 graph is populated, MCP tools should prefer graph queries over validator-heuristic text matching for any grounding question.
- Phase 4 MCP tools become truly language-generic. `get_callers()` works the same way on any language with a `.scm` file. No per-tool language branching.
- Future Phase 6 verification policies can target structural invariants that apply across languages (e.g. "no method on an `@RestController` calls a method on a `@Repository` directly"), because the graph abstracts away language specifics.
- This decision retroactively constrains the fix from T-FIX-001: any future validator enhancements must be moved toward the same declarative pattern or scoped clearly as "Phase 1 temporary pragma, not a Phase 2+ precedent".
