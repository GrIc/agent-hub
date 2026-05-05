# Phase 2 — GraphRAG = World Model (v2, language-agnostic)

> **Mode**: `graph-engineer` (see `.roomodes`).
> **Effort**: 3 weeks.
> **Prerequisite**: Phase 1 shipped (validator no longer blocks scans).
> **Parallelizable with**: Phase 3 (Changelog), Phase 4 (MCP framework).
> **Replaces**: previous Phase 2 document (which leaked language-specific code into Python).

---

## 0. The cardinal rule (READ FIRST)

Phase 1's validator fix taught us a painful lesson: hard-coding Java/Python heuristics works for CATIA but destroys the product's generic positioning. **Phase 2 must not repeat that mistake.**

**The rule, absolute and non-negotiable:**

> All language-specific logic lives in **`queries/<lang>.scm`** files (tree-sitter query language).
> All Python code in `src/graph/` is **language-agnostic**.
>
> Adding a new language = dropping one `.scm` file. Zero Python changes.

If a Roo agent writes `if language == "java":` inside any file under `src/graph/`, the code is wrong. The only exception is the thin `parsers.py` loader that maps language name → tree-sitter Language object.

---

## 1. What a "world model" actually is

A world model of a codebase has three layers. Only one is language-specific, and even that one is declarative, not imperative.

```
┌──────────────────────────────────────────────────────────────────┐
│ Layer 3 — SEMANTIC (grounded LLM)                                │
│ "What does this module do? What's its business intent?"          │
│ LANGUAGE-AGNOSTIC. Consumes Layer 2 outputs.                     │
│ Uses Phase 1 grounding. Lives in src/graph/enricher.py.          │
├──────────────────────────────────────────────────────────────────┤
│ Layer 2 — STRUCTURAL (tree-sitter AST + declarative queries)     │
│ "What classes/functions/imports exist? Who calls what?"          │
│ LANGUAGE-AGNOSTIC Python. Per-language queries in queries/*.scm. │
│ Lives in src/graph/extractor.py + queries/.                      │
├──────────────────────────────────────────────────────────────────┤
│ Layer 1 — TOPOLOGICAL (filesystem + git)                         │
│ "What files? What directories? What changed when?"               │
│ FULLY LANGUAGE-AGNOSTIC. No parser needed.                       │
│ Lives in src/graph/topology.py.                                  │
└──────────────────────────────────────────────────────────────────┘
```

Every MCP tool in Phase 4 answers a question. That question maps to one of these three layers. The tool framework doesn't know or care about Java vs Python vs Rust. It asks the graph store; the graph store answers.

---

## 2. The tree-sitter query approach in 5 minutes

Tree-sitter ships with ~160 grammars, each a C library with Python bindings. Each grammar parses a language into a typed AST. You extract what you need via **queries** in a Scheme-like DSL.

Example — extract classes and methods from Java:

```scheme
; queries/java.scm

; Classes, interfaces, enums, records
(class_declaration       name: (identifier) @class.name) @class.def
(interface_declaration   name: (identifier) @class.name) @class.def
(enum_declaration        name: (identifier) @class.name) @class.def
(record_declaration      name: (identifier) @class.name) @class.def

; Methods
(method_declaration name: (identifier) @method.name) @method.def

; Calls
(method_invocation name: (identifier) @call.target) @call.site

; Imports
(import_declaration (scoped_identifier) @import.path) @import.site

; Annotations (useful for Service detection)
(marker_annotation name: (identifier) @annotation.name)
(annotation        name: (identifier) @annotation.name)
```

Same extraction for Python:

```scheme
; queries/python.scm
(class_definition     name: (identifier) @class.name) @class.def
(function_definition  name: (identifier) @method.name) @method.def
(call                 function: (identifier) @call.target) @call.site
(import_statement     name: (dotted_name) @import.path) @import.site
```

For Go:

```scheme
; queries/go.scm
(type_declaration (type_spec name: (type_identifier) @class.name)) @class.def
(function_declaration name: (identifier) @method.name) @method.def
(call_expression function: (identifier) @call.target) @call.site
```

**The Python code reading these is identical across languages.** It loads the query, runs it against the parsed tree, reads captures by name (`@class.name`, `@call.target`), emits graph nodes and edges.

This is how Semgrep, Sourcegraph, GitHub's code navigation, and nvim-treesitter all work. It's a solved pattern. We just apply it.

---

## 3. The universal capture vocabulary

Every `.scm` file must use the same capture names. Graph extractor reads them blindly.

| Capture | Meaning | Emits |
|---------|---------|-------|
| `@module.def` | Package/namespace declaration | Node: `Module` |
| `@class.def` / `@class.name` | Type definition (class/interface/struct/trait/enum) | Node: `Class` |
| `@method.def` / `@method.name` | Function/method definition | Node: `Method` |
| `@field.def` / `@field.name` | Field/attribute/property | Node: `Field` |
| `@call.site` / `@call.target` | Function call expression | Edge: `calls` |
| `@import.site` / `@import.path` | Import/use/require statement | Edge: `imports` |
| `@extends.target` | Superclass reference | Edge: `extends` |
| `@implements.target` | Interface reference | Edge: `implements` |
| `@annotation.name` | Annotation / decorator | Node metadata |

A language whose `.scm` file only captures `@class.def` and `@method.def` is still valuable — it just contributes less to the graph. No hard fallback; partial data is fine.

---

## 4. Phase 2 deliverables (v2)

| ID | Deliverable | Effort |
|----|-------------|--------|
| `src/graph/store.py` | SQLite-backed graph store (unchanged from v1 spec) | 2d |
| `src/graph/parsers.py` | Tree-sitter language loader. The ONLY language-aware file. | 0.5d |
| `src/graph/extractor.py` | Language-agnostic extractor that runs any `.scm` against any AST | 2d |
| `src/graph/topology.py` | Filesystem + git layer (zero parsers) | 1d |
| `src/graph/resolver.py` | Cross-file name → FQN resolution (language-agnostic heuristic) | 2d |
| `src/graph/enricher.py` | LLM semantic enrichment (grounded, language-agnostic) | 2d |
| `queries/java.scm` | Java captures | 0.5d |
| `queries/python.scm` | Python captures | 0.5d |
| `queries/javascript.scm` | JavaScript captures | 0.5d |
| `queries/typescript.scm` | TypeScript captures | 0.5d |
| `queries/go.scm` | Go captures | 0.5d |
| `queries/_test_fixtures/*` | Fixtures per language (5 files each) | 1d |
| `build_graph.py` | Orchestrator (rewritten as a thin driver) | 1d |
| `tests/test_graph_language_parity.py` | Proves all queries produce comparable output shape | 1d |
| `config.yaml` | `graph.*` section (paths, supported languages, fallback policy) | 0.2d |

Total: ~15 engineer-days. 3 weeks with buffer.

---

## 5. Task list

### T-201 — Config schema in `config.yaml`

**Mode**: `graph-engineer`
**Effort**: 0.2 day

**CHANGES**: add to `config.yaml`:

```yaml
graph:
  store: sqlite
  db_path: .graphdb/graph.sqlite
  queries_dir: queries               # where .scm files live
  supported_languages:               # keys must match filenames in queries_dir
    - java
    - python
    - javascript
    - typescript
    - go
  # Extension → language mapping. Keep this config-driven so new languages
  # require zero code changes.
  extensions:
    .java: java
    .py: python
    .js: javascript
    .jsx: javascript
    .ts: typescript
    .tsx: typescript
    .go: go
  # Unknown extensions fall through to topological layer only.
  unknown_language_policy: topology_only   # or: "skip" to ignore entirely
  hub_dampening:
    enabled: true
    threshold: 0.20
    factor: 0.30
```

**ACCEPTANCE**: config loads; missing `queries/<lang>.scm` for a listed language raises a clear error at startup ("graph.supported_languages includes 'rust' but queries/rust.scm does not exist").

---

### T-202 — `src/graph/store.py` (SQLite backend)

*Identical to the v1 Phase 2 task. See original doc. ~2 days.*

---

### T-203 — `src/graph/parsers.py` — the ONLY language-aware file

**Mode**: `graph-engineer`
**Effort**: 0.5 day

**CONTEXT**: one small module that maps `"java"` → tree-sitter `Language` object. This is the ONLY place where we tolerate per-language imports, because tree-sitter needs them.

**FILES** (NEW): `src/graph/parsers.py`

```python
"""Language loaders for tree-sitter.

The only module in src/graph/ allowed to import language-specific packages.
Every downstream consumer gets back a uniform (Parser, Language) pair.

To add a new language:
  1. pip install tree-sitter-<lang>
  2. Add one entry to _LANG_LOADERS below.
  3. Create queries/<lang>.scm.
  4. Add the mapping in config.yaml: graph.extensions.

No other file in src/graph/ changes.
"""

from functools import lru_cache
from typing import Callable

from tree_sitter import Language, Parser


def _load_java() -> Language:
    import tree_sitter_java
    return Language(tree_sitter_java.language())


def _load_python() -> Language:
    import tree_sitter_python
    return Language(tree_sitter_python.language())


def _load_javascript() -> Language:
    import tree_sitter_javascript
    return Language(tree_sitter_javascript.language())


def _load_typescript() -> Language:
    import tree_sitter_typescript
    return Language(tree_sitter_typescript.language_typescript())


def _load_go() -> Language:
    import tree_sitter_go
    return Language(tree_sitter_go.language())


_LANG_LOADERS: dict[str, Callable[[], Language]] = {
    "java":       _load_java,
    "python":     _load_python,
    "javascript": _load_javascript,
    "typescript": _load_typescript,
    "go":         _load_go,
}


@lru_cache(maxsize=None)
def get_parser(language: str) -> tuple[Parser, Language] | None:
    """Return (Parser, Language) or None if unavailable."""
    loader = _LANG_LOADERS.get(language)
    if loader is None:
        return None
    try:
        lang = loader()
    except ImportError:
        return None
    parser = Parser(lang)
    return parser, lang


def supported_languages() -> list[str]:
    return sorted(_LANG_LOADERS.keys())
```

**ACCEPTANCE**:
- `pytest tests/test_parsers.py` passes with `test_each_supported_language_loads`.
- Adding Rust = adding `_load_rust` + pip package + one dict entry.

**ANTI-PATTERNS**:
- Do NOT let callers check `language == "java"`. Give them the loaded parser and an opaque language name.
- Do NOT cache the parsed tree here; caching belongs upstream.

---

### T-204 — `src/graph/extractor.py` — language-agnostic extractor

**Mode**: `graph-engineer`
**Effort**: 2 days

**CONTEXT**: takes a file + its language → returns (nodes, edges). Internally, loads the appropriate `.scm` query, runs it against the parsed tree, maps captures to graph records.

**FILES** (NEW): `src/graph/extractor.py`

```python
"""Language-agnostic structural extractor.

For each (file, language) pair:
  1. Get (parser, lang) via parsers.get_parser().
  2. Parse source → tree.
  3. Load queries/<language>.scm and compile it against lang.
  4. Run query.captures(tree.root_node).
  5. Group captures by enclosing def (class.def wraps method.def, etc.).
  6. Emit graph nodes + edges using only capture names.

No language-specific branching. If the .scm file doesn't capture @field.def,
no Field nodes are emitted for that language — the graph is simply less rich.

API:
    extract_from_file(
        file_path: str,
        source_bytes: bytes,
        language: str,
        queries_dir: str,
    ) -> tuple[list[NodeRecord], list[EdgeRecord]]
"""

from dataclasses import dataclass, field
from pathlib import Path

from tree_sitter import Query, Node

from src.graph.parsers import get_parser


@dataclass
class NodeRecord:
    id: str
    type: str       # "Module" | "Class" | "Method" | "Field"
    name: str
    file_path: str
    line_start: int
    line_end: int
    metadata: dict = field(default_factory=dict)


@dataclass
class EdgeRecord:
    source_id: str
    target_id: str  # may be a placeholder for unresolved
    relation: str   # "contains" | "calls" | "imports" | "extends" | "implements"
    evidence_path: str
    evidence_line: int
    metadata: dict = field(default_factory=dict)


# Capture name → (emission_kind, graph_type)
_CAPTURE_SCHEMA = {
    "module.def":       ("node", "Module"),
    "class.def":        ("node", "Class"),
    "method.def":       ("node", "Method"),
    "field.def":        ("node", "Field"),
    "call.site":        ("edge", "calls"),
    "import.site":      ("edge", "imports"),
    "extends.target":   ("edge", "extends"),
    "implements.target":("edge", "implements"),
    "annotation.name":  ("metadata", "annotation"),
}


def _load_query(language: str, queries_dir: str, lang) -> Query | None:
    path = Path(queries_dir) / f"{language}.scm"
    if not path.exists():
        return None
    return Query(lang, path.read_text(encoding="utf-8"))


def extract_from_file(
    file_path: str,
    source_bytes: bytes,
    language: str,
    queries_dir: str,
) -> tuple[list[NodeRecord], list[EdgeRecord]]:
    loaded = get_parser(language)
    if loaded is None:
        return [], []
    parser, lang = loaded

    query = _load_query(language, queries_dir, lang)
    if query is None:
        return [], []

    tree = parser.parse(source_bytes)
    captures = query.captures(tree.root_node)

    nodes: list[NodeRecord] = []
    edges: list[EdgeRecord] = []

    # Walk captures, grouping by enclosing .def captures via parent traversal.
    # Implementation details: use node.parent to climb up to the nearest
    # *.def capture; that tells us the "enclosing declaration" for scoping.
    # Also track (class.def → method.def) nesting to emit "contains" edges.
    ...

    return nodes, edges
```

Full implementation follows standard tree-sitter-query patterns — a Roo agent fluent in tree-sitter can write it in a half-day. If not, point them at the nvim-treesitter or py-tree-sitter-queries repos for reference.

**ACCEPTANCE**:
- Same 5 fixtures per language (T-206) produce structurally-equivalent outputs:
  * number of class nodes matches expected per fixture,
  * each class has `contains` edges to its methods,
  * calls are emitted with target names (resolved later).
- `extract_from_file(...)` on a 5000-line Java file completes in < 500 ms.

**ANTI-PATTERNS**:
- NO `if language == "..."` anywhere in this file.
- NO per-language special-casing for name resolution — that's T-205.
- NO LLM calls.

---

### T-205 — `src/graph/resolver.py` — heuristic FQN resolution

**Mode**: `graph-engineer`
**Effort**: 2 days

**CONTEXT**: the extractor emits `calls` edges with target = simple name (e.g. `foo`). The resolver walks the import graph + intra-module declarations to rewrite targets as FQNs. Same heuristic for all languages: **look up the simple name in the file's imports; if found, use the qualified name; else mark unresolved with `confidence: 0.5`**.

Unlike v1, the resolver is explicitly language-agnostic: imports are stored as `(src_file, imported_symbol, imported_from)` tuples in the graph, and lookup uses those tuples. No Java-specific or Python-specific logic.

**ACCEPTANCE**: resolution rate ≥ 70% on the user's workspace (mixed Java + Python); fewer false-resolutions than unresolveds (i.e. don't over-resolve).

---

### T-206 — `queries/*.scm` + fixtures for 5 languages

**Mode**: `graph-engineer`
**Effort**: 2.5 days total (0.5 day per language)

**CONTEXT**: drop-in query files for the 5 Phase 2 languages. Each `.scm` is short (~30-50 lines) and follows the capture vocabulary in §3 above.

**FILES** (NEW):

- `queries/java.scm`
- `queries/python.scm`
- `queries/javascript.scm`
- `queries/typescript.scm`
- `queries/go.scm`
- `queries/_test_fixtures/java/{simple,generics,annotations,nested,calls}.java`
- `queries/_test_fixtures/python/{simple,decorators,async,dataclass,calls}.py`
- (similar for js/ts/go)

**ACCEPTANCE**: each `.scm` runs against its 5 fixtures and produces the expected number of `@class.def`, `@method.def`, `@call.site` captures.

**ANTI-PATTERNS**:
- Don't overcomplicate. A `.scm` that captures only `class.def` and `method.def` is already useful. Richer captures can come later.
- Don't cherry-pick captures to make the LLM look good. Structural accuracy over aesthetic.

---

### T-207 — `src/graph/topology.py` — filesystem + git layer

**Mode**: `graph-engineer`
**Effort**: 1 day

**CONTEXT**: some structural information needs no parser:
- Directory tree → `Module contains Module` edges.
- File path → `Module contains File` (File = a special Node type).
- Git blame → `Method last_changed_by commit X`.
- File co-change frequency (from git log) → `File co_changes_with File` edges, weighted.

This layer works on **every** file regardless of language — even files we can't parse (configs, docs, images). For a file with no AST extraction, this is the only layer populated. The graph is partial but not empty.

**FILES** (NEW): `src/graph/topology.py` with functions:
- `emit_directory_tree(workspace) → nodes + contains-edges`
- `emit_file_nodes(workspace) → File nodes (one per indexed file)`
- `emit_co_change_edges(repo, since_days=180) → weighted File-File edges`

**ACCEPTANCE**: on the user's CATIA workspace, the graph has ≥10k File nodes and ≥20k directory-contains edges even without any language parser firing.

---

### T-208 — `src/graph/enricher.py` — language-agnostic LLM enrichment

**Mode**: `graph-engineer` + `kip-engineer`
**Effort**: 2 days

**CONTEXT**: for each `Class` and `Service` node, generate a 1-2 sentence grounded description + intent classification. Uses Phase 1 grounding (via `prepend_grounding`). **No per-language prompts** — the prompt templates work for any language because they consume the AST-extracted node's neighborhood (callers, callees, methods, annotations), not the source language.

Example prompt (same for Java, Python, Go, Rust):

```
You describe a code entity based on its AST neighborhood.

Entity: class {name}
File: {path}:{lines}
Methods: {method_names}
Outgoing calls: {callee_names}
Imports used: {imports}
Annotations: {annotations}

Source excerpt:
```
{source}
```

Produce strict JSON:
{
  "description": "1-2 sentences, max 200 chars",
  "intent": "data_access|business_logic|controller|util|config|test|other",
  "confidence": 0.0 to 1.0
}

If unclear, use intent="other" and description="[INSUFFICIENT_EVIDENCE]".
```

**ACCEPTANCE**: same success criteria as v1 Phase 2 enricher.

---

### T-209 — `build_graph.py` orchestrator rewrite

**Mode**: `graph-engineer`
**Effort**: 1 day

**CONTEXT**: a thin driver. Walks workspace, routes each file through:
1. Topology layer (always).
2. Structural layer if `config.graph.extensions` maps the extension to a supported language.
3. Resolution + hub dampening passes after all files processed.
4. Optional `--enrich` for Layer 3.

**ACCEPTANCE**: on user's workspace:
- Topology-only files (XML, YAML, MD, CSV) produce File nodes + topology edges.
- Java and Python files additionally produce Class/Method nodes.
- Full run < 10 min without enrichment.

---

### T-210 — `tests/test_graph_language_parity.py` — the critical test

**Mode**: `graph-engineer`
**Effort**: 1 day

**CONTEXT**: this test **enforces** the language-agnostic principle. It constructs a "Hello World class with one method that calls another" fixture in every supported language. After extraction, all graphs must have:
- 1 `Class` node
- 2 `Method` nodes
- 1 `Class contains Method` edge (actually 2: one per method)
- 1 `Method calls Method` edge

If the Python query gives 2 classes and the Go query gives 0, the test fails and someone must update the `.scm` file. This test is how we know the capture vocabulary is being honored.

**ACCEPTANCE**: test passes across all 5 languages. A deliberately-broken `.scm` file fails the test with a readable diff.

**This test is the heart of Phase 2's genericity.** Don't skip it.

---

## 6. Phase 2 success gate (v2)

Before marking Phase 2 complete:

- [ ] `queries/*.scm` exists for all 5 supported languages.
- [ ] `src/graph/` contains zero `if language == ...` branches outside `parsers.py`.
- [ ] `tests/test_graph_language_parity.py` passes.
- [ ] On user's CATIA workspace: `build_graph.py` produces a graph with ≥10k nodes, ≥30k edges, ≥70% call resolution rate.
- [ ] Topology-only nodes exist for non-source files (configs, XML, CSV).
- [ ] Adding a hypothetical 6th language (e.g. Rust) requires:
  * One new file: `queries/rust.scm` (~40 lines).
  * Three lines added to `parsers.py::_LANG_LOADERS`.
  * Two lines added to `config.yaml::graph.extensions`.
  * **Zero Python code changes in `src/graph/extractor.py`, `resolver.py`, `enricher.py`, or `store.py`.**

If the last point fails, go back and refactor until it holds. That's the whole point.

---

## 7. What this buys us

**For the user**: the "world model" now actually exists as a queryable graph, not as a pile of regex heuristics. MCP tools in Phase 4 can ask "who calls `UserService.save`?" and get a real answer from the graph store, not an LLM guess.

**For the product**: we can honestly say "works on any language with a tree-sitter grammar" (that's every mainstream language plus most niche ones). We're not bluffing. The test suite enforces it.

**For Phase 1's fallout**: the Java-specific validator fix from T-FIX-001 is a temporary pragma for Phase 1 only. Phase 2 does not propagate that pattern. The validator-vs-extractor split lets us put language-specific complexity exactly where it belongs: in declarative `.scm` files, nowhere else.

---

## 8. Migration note — what to do with the existing Phase 2 code

The repo currently has a `build_graph.py` that uses LLM triplet extraction. That's v0. The v1 spec (previous Phase 2 doc) upgraded it with tree-sitter but still mixed Python heuristics per language. **v2 replaces both.**

Roo steps:
1. Rename current `build_graph.py` → `build_graph.v0.py.bak` (keep for reference).
2. Execute T-202 through T-210 in order.
3. Delete the `.bak` file once the new pipeline is verified.
4. The old `.graphdb/graph.json` is thrown away; the SQLite DB starts fresh.

---

## 9. Files summary (Phase 2 v2)

| File | Status |
|------|--------|
| `src/graph/store.py` | NEW |
| `src/graph/parsers.py` | NEW (only lang-aware file) |
| `src/graph/extractor.py` | NEW (agnostic) |
| `src/graph/resolver.py` | NEW (agnostic) |
| `src/graph/topology.py` | NEW (agnostic, no parser) |
| `src/graph/enricher.py` | NEW (agnostic) |
| `queries/java.scm` | NEW |
| `queries/python.scm` | NEW |
| `queries/javascript.scm` | NEW |
| `queries/typescript.scm` | NEW |
| `queries/go.scm` | NEW |
| `queries/_test_fixtures/**` | NEW |
| `build_graph.py` | REWRITTEN |
| `config.yaml` | MODIFIED (graph.* section) |
| `requirements.txt` | MODIFIED (tree-sitter + 5 language packages) |
| `tests/test_graph_*.py` | NEW (5 files) |
| `tests/test_graph_language_parity.py` | NEW (the key test) |

---

*End of Phase 2 v2. The `graph-engineer` Roo mode with the `ast-extraction` skill is the right context for these tasks. Load them both.*
