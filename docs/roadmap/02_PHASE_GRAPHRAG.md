# Phase 2 — GraphRAG Investment (DECIDE-5)

> **Mode**: `graph-engineer` (see `.roomodes`).
> **Effort**: 3 weeks.
> **Prerequisite**: Phase 1 complete (specifically T-102 — tree-sitter extractor).
> **Parallelizable with**: Phase 3 (Changelog) and Phase 4 (MCP tools framework — but NOT graph tools, which depend on this).

---

## 1. Re-evaluation of `build_graph.py`

The current `build_graph.py` uses an LLM to extract entity-relation triplets from documentation. This was the right call when LLMs were cheap and structural accuracy didn't matter. **Both assumptions are now wrong.**

DECIDE-5 says "invest". Investment means: **structural triplets come from AST, not LLM**. The LLM is reserved for *semantic* enrichment (intent, descriptions, business meaning). This split eliminates the entire class of structural hallucinations.

**Architecture pivot**:

```
OLD:  source code → LLM → triplets (high hallucination rate)
NEW:  source code → tree-sitter AST → structural triplets (zero hallucination)
                                ↓
                          LLM enrichment → descriptions, intent (grounded against AST)
```

---

## 2. Phase 2 deliverables

| ID | Deliverable | Lines (est.) |
|----|-------------|--------------|
| `src/graph/store.py` | SQLite-backed graph store + queries | ~400 |
| `src/graph/extractor_ast.py` | AST-based structural triplet extractor | ~500 |
| `src/graph/enricher.py` | LLM semantic enrichment with grounding | ~250 |
| `src/graph/validator.py` | Triplet validation against config schema | ~150 |
| Updated `build_graph.py` | Orchestrator using the new modules | (rewrite) |
| Updated `config.yaml` | `knowledge_graph.*` section | (modify) |
| `tests/test_graph_extractor.py` | AST extraction golden tests | ~300 |

---

## 3. Tasks

### T-201 — Define the graph schema in `config.yaml`

**Mode**: `graph-engineer`
**Effort**: 0.5 day
**Depends on**: nothing.

**CONTEXT**
The schema is the contract. Lock it in config first; then code can validate against it.

**FILE TO MODIFY**: `config.yaml`

Append:

```yaml
knowledge_graph:
  store: sqlite                  # sqlite (default) | kuzu (Phase 5+ if scale demands)
  db_path: .graphdb/graph.sqlite

  node_types:
    - Module          # a directory or namespace
    - Package         # a Java package or Python module
    - Class           # a class, interface, enum, record
    - Method          # a function or method
    - Field           # a class member or top-level variable
    - Service         # a class annotated as service / known DI bean
    - Endpoint        # an HTTP route / RPC handler
    - Config          # a configuration file or class
    - Test            # a test class or test function

  relation_types:
    - contains        # parent → child (Module contains Class)
    - depends_on      # generic dependency (Module depends_on Module)
    - imports         # explicit import statement
    - calls           # method calls method
    - implements      # class implements interface
    - extends         # class extends class
    - reads           # method reads field
    - writes          # method writes field
    - exposes         # service exposes endpoint
    - configured_by   # entity configured_by Config
    - tested_by       # entity tested_by Test

  # Which relations are valid between which node types.
  # Triplets violating this matrix are rejected.
  allowed:
    Module: [contains, depends_on, imports]
    Package: [contains, depends_on, imports]
    Class: [extends, implements, contains, calls, imports, configured_by, tested_by]
    Method: [calls, reads, writes, tested_by]
    Field: [reads, writes]
    Service: [exposes, depends_on, calls, configured_by]
    Endpoint: [calls]
    Config: [configures]
    Test: [tested_by]

  hub_dampening:
    enabled: true
    threshold: 0.20    # nodes connected to > threshold of all nodes get dampened
    factor: 0.30       # weight multiplier for hub edges in retrieval
```

**ACCEPTANCE**
- Config loads without error.
- A new util `src/graph/validator.py: validate_schema(config) -> None` is callable and raises on inconsistency (e.g. an `allowed` value referencing a non-existent relation).

**ANTI-PATTERNS**
- Do NOT add node types speculatively. Add only what's used.
- Do NOT make the matrix fully permissive ("any relation between any nodes"). Strictness is the point.

---

### T-202 — Build `src/graph/store.py` (SQLite-backed graph)

**Mode**: `graph-engineer`
**Effort**: 2 days
**Depends on**: T-201.

**CONTEXT**
We need a queryable, incremental graph store. SQLite is sufficient up to ~1M nodes (the user's codebase is well within this). Kuzu is reserved for later if scale demands.

**FILE**: `src/graph/store.py`

```python
"""SQLite-backed knowledge graph store.

Schema (in DDL form, see _SCHEMA constant below):
- nodes(id TEXT PRIMARY KEY, type TEXT, name TEXT, file_path TEXT,
        line_start INT, line_end INT, source_hash TEXT, metadata_json TEXT)
- edges(id INTEGER PRIMARY KEY, source_id TEXT, target_id TEXT, relation TEXT,
        weight REAL, evidence_path TEXT, evidence_line INT, metadata_json TEXT,
        FOREIGN KEY (source_id) REFERENCES nodes(id),
        FOREIGN KEY (target_id) REFERENCES nodes(id))
- meta(key TEXT PRIMARY KEY, value TEXT)
- file_state(file_path TEXT PRIMARY KEY, source_hash TEXT, indexed_at TEXT)

Indexes:
- idx_nodes_type, idx_nodes_file, idx_nodes_name
- idx_edges_source, idx_edges_target, idx_edges_relation

API:
    store = GraphStore(db_path)
    store.upsert_node(id, type, name, file_path, line_start, line_end, source_hash, metadata)
    store.upsert_edge(source_id, target_id, relation, weight, evidence_path, evidence_line, metadata)
    store.get_callers(symbol_id, limit) -> list[Edge]
    store.get_callees(symbol_id, depth) -> list[Edge]
    store.shortest_path(from_id, to_id) -> list[str] | None  # via networkx temporarily loaded
    store.preview_impact(file_paths: list[str]) -> dict[str, float]  # impacted module → score
    store.find_hub_modules(threshold) -> list[tuple[str, float]]
    store.delete_for_file(file_path) -> int  # for incremental updates
    store.stats() -> dict
"""

import sqlite3, json
from pathlib import Path
from contextlib import contextmanager

_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  name TEXT NOT NULL,
  file_path TEXT,
  line_start INTEGER,
  line_end INTEGER,
  source_hash TEXT,
  metadata_json TEXT
);
CREATE TABLE IF NOT EXISTS edges (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id TEXT NOT NULL,
  target_id TEXT NOT NULL,
  relation TEXT NOT NULL,
  weight REAL DEFAULT 1.0,
  evidence_path TEXT,
  evidence_line INTEGER,
  metadata_json TEXT,
  FOREIGN KEY (source_id) REFERENCES nodes(id),
  FOREIGN KEY (target_id) REFERENCES nodes(id),
  UNIQUE (source_id, target_id, relation)
);
CREATE TABLE IF NOT EXISTS file_state (
  file_path TEXT PRIMARY KEY,
  source_hash TEXT NOT NULL,
  indexed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
CREATE INDEX IF NOT EXISTS idx_nodes_file ON nodes(file_path);
CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_relation ON edges(relation);
"""

class GraphStore:
    def __init__(self, db_path: str | Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), isolation_level=None)
        self._conn.executescript(_SCHEMA)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

    # --- writes ---
    def upsert_node(self, *, id: str, type: str, name: str,
                    file_path: str | None = None,
                    line_start: int | None = None,
                    line_end: int | None = None,
                    source_hash: str | None = None,
                    metadata: dict | None = None) -> None:
        ...

    def upsert_edge(self, *, source_id: str, target_id: str, relation: str,
                    weight: float = 1.0,
                    evidence_path: str | None = None,
                    evidence_line: int | None = None,
                    metadata: dict | None = None) -> None:
        # uses INSERT OR REPLACE based on UNIQUE constraint
        ...

    def delete_for_file(self, file_path: str) -> int:
        """Remove all nodes/edges originating from this file. Returns count deleted."""
        ...

    # --- queries ---
    def get_callers(self, symbol_id: str, limit: int = 50) -> list[dict]: ...
    def get_callees(self, symbol_id: str, depth: int = 1) -> list[dict]: ...
    def shortest_path(self, from_id: str, to_id: str) -> list[str] | None: ...
    def preview_impact(self, file_paths: list[str]) -> dict[str, float]: ...
    def find_hub_modules(self, threshold: float) -> list[tuple[str, float]]: ...

    def stats(self) -> dict:
        return {
            "nodes": self._conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
            "edges": self._conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
            "files": self._conn.execute("SELECT COUNT(*) FROM file_state").fetchone()[0],
        }
```

**Note on shortest_path / preview_impact**: load the relevant subgraph into networkx on demand (not the full graph). Cap subgraph size at 10k nodes; if exceeded, return a partial result with a `truncated: true` flag.

**ACCEPTANCE**
- `python -c "from src.graph.store import GraphStore; s = GraphStore('test.db'); s.upsert_node(id='X', type='Class', name='X'); print(s.stats())"` works.
- Re-opening the DB preserves data.
- `delete_for_file('foo.java')` removes all nodes whose `file_path == 'foo.java'` AND any edges referencing them.
- Unit tests in `tests/test_graph_store.py` cover: upsert idempotency, delete cascade, callers/callees on a 100-node fixture.

**ANTI-PATTERNS**
- Do NOT load the full graph in memory for every query — use indexed SQL.
- Do NOT use `pickle` for metadata — JSON only (debuggability).
- Do NOT introduce a Cypher-like query DSL. Stick to typed methods.

---

### T-203 — AST-based structural extractor `src/graph/extractor_ast.py`

**Mode**: `graph-engineer`
**Effort**: 5 days (the heart of Phase 2)
**Depends on**: T-102 (identifiers), T-202.

**CONTEXT**
This is where the value lives. We extract structural triplets from source via tree-sitter AST. **Zero LLM calls in this module.**

For each supported language (Java, Python in Phase 2; TS/JS/Go later), implement:

| Triplet kind | How to detect (Java example) |
|--------------|------------------------------|
| `Module contains Class` | `class_declaration` parent → `class_declaration` child |
| `Class extends Class` | `superclass` field of `class_declaration` |
| `Class implements Interface` | `super_interfaces` field |
| `Class contains Method` | `method_declaration` inside `class_body` |
| `Method calls Method` | `method_invocation` nodes (resolved by name) |
| `Method reads/writes Field` | `field_access` / assignment LHS |
| `Module imports Module` | `import_declaration` |
| `Class is Service` | annotation `@Service`, `@Component`, or matches DI heuristic |
| `Service exposes Endpoint` | annotation `@RestController`/`@RequestMapping` paired with `@GetMapping` etc. |
| `Class tested_by Test` | test class name pattern `*Test`, `*Spec` references the SUT in imports |

**File**: `src/graph/extractor_ast.py`

```python
"""Structural triplet extraction from source code via tree-sitter AST.

For each source file, returns a list of (node_dicts, edge_dicts) ready for GraphStore.

ZERO LLM CALLS. Pure AST traversal. If a fact cannot be determined from the AST,
it is NOT extracted — there is no inference, no guessing.
"""

from src.rag.identifiers import detect_language, _get_parser

def extract_from_file(file_path: str, source: str) -> tuple[list[dict], list[dict]]:
    """Return (nodes, edges).

    nodes: [{id, type, name, file_path, line_start, line_end, metadata}]
    edges: [{source_id, target_id, relation, evidence_path, evidence_line}]

    id format: "<type>:<file_path>:<name>" for class/method/field
               "<type>:<dotted_path>" for module/package
    """
    lang = detect_language(file_path)
    if lang == "java":
        return _extract_java(file_path, source)
    if lang == "python":
        return _extract_python(file_path, source)
    return [], []  # unsupported


def _extract_java(file_path: str, source: str) -> tuple[list[dict], list[dict]]:
    parser = _get_parser("java")
    if parser is None:
        return [], []
    tree = parser.parse(source.encode("utf-8"))
    nodes, edges = [], []

    # walk for: package_declaration, import_declaration, class_declaration,
    # interface_declaration, method_declaration, field_declaration,
    # method_invocation, field_access, annotations.

    # Implementation details: maintain a stack of "current class" / "current method"
    # while walking, so child nodes know their parent for `contains` edges.

    # ID resolution for `calls`: the AST gives us the unqualified callee name.
    # For Phase 2 we record edges by name; full FQN resolution happens in T-204
    # (a post-pass that joins on imports).

    return nodes, edges
```

**ID resolution strategy** (important):
- Phase 2.A: extract by simple name (e.g. `calls foo()` → edge `Method:current_method → Method:foo`).
- Phase 2.B (T-204): post-pass that resolves `foo` to the FQN by checking imports of the current file. Edges that can't be resolved get a `confidence: 0.5` and tagged `unresolved`.

This two-pass approach avoids over-engineering AST traversal while keeping accuracy high.

**ACCEPTANCE**
- Run on the user's module (e.g. `com.example` or any well-known Java class):
  - Class node appears with correct line range.
  - All declared methods appear as `contains` edges.
  - At least 80% of method invocations within the file are extracted.
  - Imports translate to correct `imports` edges.
- Run on the project's own `synthesize.py`:
  - All `def`s appear as Method nodes.
  - Internal calls between functions appear as `calls` edges.
- Unit tests in `tests/test_graph_extractor.py` cover at least 5 hand-crafted Java fixtures with snapshot triplets.

**ANTI-PATTERNS**
- Do NOT call an LLM here. Ever. This module is deterministic.
- Do NOT generate edges for tokens that are not declarations (e.g. a method body referencing `String` should NOT create a `calls String` edge).
- Do NOT block on FQN resolution — record unresolved with low confidence.

---

### T-204 — FQN resolution post-pass + import graph

**Mode**: `graph-engineer`
**Effort**: 2 days
**Depends on**: T-203.

**CONTEXT**
After T-203 extracts edges by simple name, this pass resolves them to fully qualified names using the import table. Unresolved edges are kept with `confidence: 0.5` and `unresolved: true` flags.

**FILE**: `src/graph/resolver.py`

```python
"""Post-extraction pass: resolve simple-name edges to FQN edges using the import graph.

For each file:
  - Build {short_name → FQN} from import declarations + intra-package references.
  - For each edge whose target is a simple name, attempt resolution.
  - On success: rewrite target_id to the FQN, set confidence=1.0.
  - On failure: keep simple-name target, set confidence=0.5, unresolved=True.
"""

def resolve_edges(store: GraphStore) -> dict:
    """Mutates the store in place. Returns stats: {resolved, unresolved, total}."""
    ...
```

**ACCEPTANCE**
- After extracting + resolving on the user's workspace, ≥70% of `calls` edges have `unresolved=False`.
- Unresolved edges are queryable: `store.get_unresolved_edges()` returns them for inspection.

**ANTI-PATTERNS**
- Do NOT delete unresolved edges. Low confidence is more useful than absence.
- Do NOT bring in a full Java type system — heuristic resolution via imports + same-package is enough.

---

### T-205 — Semantic enrichment via LLM (grounded against AST)

**Mode**: `graph-engineer` + `kip-engineer`
**Effort**: 2 days
**Depends on**: T-204, Phase 1 grounding.

**CONTEXT**
The AST gives us structure. The LLM gives us **meaning**: "what does this class do? what is its business intent?" But the LLM can only describe nodes that AST already extracted — it cannot invent new ones. This is the strict separation.

**FILE**: `src/graph/enricher.py`

```python
"""LLM-based semantic enrichment of graph nodes.

For each node (typically Class and Service), call the LLM with:
  - The node's source range.
  - The list of its outgoing edges (callees, dependencies).
  - Grounding instruction (Phase 1).
Return:
  - description: 1-2 sentence purpose.
  - intent: one of {data_access, business_logic, controller, util, config, test, other}.
  - tags: list of short labels.

Stored as JSON in node.metadata. Validated:
  - No new entities mentioned in description (just text about the existing node).
  - description length capped (200 chars).
  - intent must be in the allowed enum.
"""

from src.rag.grounding import prepend_grounding, contains_abstain, ABSTAIN_TOKEN

ALLOWED_INTENTS = {"data_access", "business_logic", "controller", "util", "config", "test", "other"}

def enrich_node(store: GraphStore, node_id: str, llm_client, source_text: str) -> dict:
    ...

def enrich_all(store: GraphStore, llm_client, *, only_types: list[str] = None) -> dict:
    """Walk store, enrich nodes of given types. Returns stats."""
    ...
```

Run enrichment as a separate phase: `python build_graph.py --enrich`. It's slow (one LLM call per node) so it's optional and incremental.

**ACCEPTANCE**
- After enrichment, sample 50 random nodes — descriptions are coherent and grounded.
- `intent` field is populated and within the allowed enum.
- Re-running enrichment skips nodes whose `source_hash` is unchanged.

**ANTI-PATTERNS**
- Do NOT enrich Method or Field nodes by default — too many. Default enrichment is Class + Service only. Make it config-tunable.
- Do NOT let enrichment add edges. It only modifies node metadata.

---

### T-206 — Refactor `build_graph.py` to orchestrate the new pipeline

**Mode**: `graph-engineer`
**Effort**: 1 day
**Depends on**: T-202 through T-205.

**CONTEXT**
The old `build_graph.py` is now a thin orchestrator.

**REWRITE**: `build_graph.py`

```python
"""Build the knowledge graph from the workspace.

Pipeline:
  1. AST extraction (T-203) → nodes + edges per file.
  2. FQN resolution (T-204).
  3. (optional) Semantic enrichment (T-205).
  4. Hub dampening pass: down-weight edges from hub nodes (KIP §5.D).

CLI:
  python build_graph.py                  # incremental, no enrichment
  python build_graph.py --force          # rebuild from scratch
  python build_graph.py --enrich         # also enrich after build
  python build_graph.py --enrich-only    # only enrich, do not re-extract
  python build_graph.py --stats          # print store stats and exit
"""

from src.graph.store import GraphStore
from src.graph.extractor_ast import extract_from_file
from src.graph.resolver import resolve_edges
from src.graph.enricher import enrich_all
from src.graph.validator import validate_triplet

def main():
    ...

if __name__ == "__main__":
    main()
```

Hub dampening: after extraction, count each node's degree. Nodes with `degree > threshold * total_nodes` get their outgoing edges' weight multiplied by `factor` (from config, T-201).

**ACCEPTANCE**
- On a fresh workspace: `python build_graph.py` builds a graph with ≥10k nodes and ≥30k edges in <10 minutes (no enrichment).
- `python build_graph.py` (second run, no changes) finishes in <30 seconds (incremental).
- `python build_graph.py --stats` prints node/edge counts by type.
- `python build_graph.py --enrich --enrich-only-types Class,Service` calls the LLM only for those types.

**ANTI-PATTERNS**
- Do NOT delete the entire graph on every run. Use `delete_for_file()` for changed files only.
- Do NOT skip resolution — unresolved-everything graphs are useless.

---

### T-207 — Graph visualization endpoint `/admin/graph`

**Mode**: `roadmap-executor`
**Effort**: 1.5 days
**Depends on**: T-206.

**CONTEXT**
A read-only graph viewer for the admin dashboard. Helps humans inspect what the indexer produced. Optional but high signal.

**FILES**

`web/admin_routes.py`: add `GET /admin/graph` returning a JSON `{nodes: [...], edges: [...]}` filtered to a subgraph (default: top-100 nodes by degree). Query params: `?module=X` or `?type=Service`.

`web/admin/graph.html`: simple D3 force-directed layout (or `vis-network` from CDN).

Cap the rendered subgraph at 200 nodes to avoid browser death.

**ACCEPTANCE**
- `/admin/graph` shows an interactive force layout.
- Filtering by module reduces the set.
- Hovering a node shows its metadata.

**ANTI-PATTERNS**
- Do NOT render the full graph (1M+ nodes). Always sub-graph.
- Do NOT make the viewer write to the store.

---

## 4. Phase 2 success gate

- [ ] Tree-sitter extracts ≥95% of Java declarations from the user's fixture.
- [ ] FQN resolution rate ≥70% on calls edges.
- [ ] `python build_graph.py` incremental run on unchanged workspace: <30s.
- [ ] `store.get_callers("MyModule")` returns ≥3 real callers, zero hallucinations (every result has a verifiable file path + line).
- [ ] `/admin/graph` renders.

---

## 5. Files Phase 2 produces / modifies

| File | New / Modified |
|------|----------------|
| `src/graph/store.py` | NEW |
| `src/graph/extractor_ast.py` | NEW |
| `src/graph/resolver.py` | NEW |
| `src/graph/enricher.py` | NEW |
| `src/graph/validator.py` | NEW |
| `build_graph.py` | REWRITTEN |
| `config.yaml` | MODIFIED (knowledge_graph section) |
| `requirements.txt` | MODIFIED (networkx for path queries) |
| `tests/test_graph_*.py` | NEW (4 files) |
| `web/admin_routes.py` | MODIFIED (added /admin/graph) |
| `web/admin/graph.html` | NEW |

---

*End of Phase 2. The graph is now ready to power the `get_callers`, `get_callees`, `preview_impact` MCP tools in Phase 4.*
