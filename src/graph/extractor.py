"""Language-agnostic structural extractor.

For each (file, language) pair:
  1. Get (parser, lang) via parsers.get_parser().
  2. Parse source -> tree.
  3. Load queries/<language>.scm and compile it against lang.
  4. Run QueryCursor(query).captures(tree.root_node).
  5. Group captures by enclosing .def (class.def wraps method.def, etc.).
  6. Emit graph nodes + edges using only capture names.

No language-specific branching. If the .scm file doesn't capture @field.def,
no Field nodes are emitted for that language -- the graph is simply less rich.

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
from typing import Optional

from tree_sitter import Language, Node, Parser, Query, QueryCursor

from src.graph.parsers import get_parser


# ---------------------------------------------------------------------------
# Record types
# ---------------------------------------------------------------------------

@dataclass
class NodeRecord:
    """A node extracted from the AST."""
    id: str
    type: str            # "Module" | "Class" | "Method" | "Field"
    name: str
    file_path: str
    line_start: int
    line_end: int
    metadata: dict = field(default_factory=dict)


@dataclass
class EdgeRecord:
    """An edge extracted from the AST."""
    source_id: str
    target_id: str       # may be a placeholder for unresolved
    relation: str        # "contains" | "calls" | "imports" | "extends" | "implements"
    evidence_path: str
    evidence_line: int
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Capture schema: maps capture names to emission semantics
# ---------------------------------------------------------------------------

_CAPTURE_SCHEMA: dict[str, tuple[str, str]] = {
    "module.def":       ("node", "Module"),
    "class.def":        ("node", "Class"),
    "class.name":       ("node", "Class"),
    "method.def":       ("node", "Method"),
    "method.name":      ("node", "Method"),
    "field.def":        ("node", "Field"),
    "field.name":       ("node", "Field"),
    "call.site":        ("edge", "calls"),
    "call.target":      ("edge", "calls"),
    "import.site":      ("edge", "imports"),
    "import.path":      ("edge", "imports"),
    "extends.target":   ("edge", "extends"),
    "implements.target":("edge", "implements"),
    "annotation.name":  ("metadata", "annotation"),
}

_NODE_CAPTURES: set[str] = {
    k for k, (kind, _) in _CAPTURE_SCHEMA.items() if kind == "node"
}

_EDGE_CAPTURES: set[str] = {
    k for k, (kind, _) in _CAPTURE_SCHEMA.items() if kind == "edge"
}

_METADATA_CAPTURES: set[str] = {
    k for k, (kind, _) in _CAPTURE_SCHEMA.items() if kind == "metadata"
}


# ---------------------------------------------------------------------------
# Node identity: compare by AST position, not Python id()
# ---------------------------------------------------------------------------

def _node_key(node: Node) -> tuple:
    """Create a stable key for a tree-sitter Node based on its AST position."""
    return (
        node.type,
        node.start_point[0],
        node.start_point[1],
        node.end_point[0],
        node.end_point[1],
    )


# ---------------------------------------------------------------------------
# Query loading
# ---------------------------------------------------------------------------

def _load_query(language: str, queries_dir: str, lang) -> Optional[Query]:
    """Load and compile a .scm query file for the given language."""
    path = Path(queries_dir) / f"{language}.scm"
    if not path.exists():
        return None
    source = path.read_bytes()
    return Query(lang, source)


# ---------------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------------

def extract_from_file(
    file_path: str,
    source_bytes: bytes,
    language: str,
    queries_dir: str,
) -> tuple[list[NodeRecord], list[EdgeRecord]]:
    """Extract structural nodes and edges from a source file."""
    # Step 1: Get parser
    loaded = get_parser(language)
    if loaded is None:
        return [], []
    parser, lang = loaded

    # Step 2: Parse source
    tree = parser.parse(source_bytes)
    root_node = tree.root_node

    # Step 3: Load query
    query = _load_query(language, queries_dir, lang)
    if query is None:
        return [], []

    # Step 4: Run captures via QueryCursor
    cursor = QueryCursor(query)
    captures = cursor.captures(root_node)
    if not captures:
        return [], []

    # Step 5: Organize captures
    node_key_to_captures: dict[tuple, list[str]] = {}
    for cap_name, nodes in captures.items():
        for node in nodes:
            nk = _node_key(node)
            if nk not in node_key_to_captures:
                node_key_to_captures[nk] = []
            node_key_to_captures[nk].append(cap_name)

    # Build a lookup from node_key to the first Node object found
    node_key_to_node: dict[tuple, Node] = {}
    for cap_name, nodes in captures.items():
        for node in nodes:
            nk = _node_key(node)
            if nk not in node_key_to_node:
                node_key_to_node[nk] = node

    # Identify .def nodes
    def_node_keys: set[tuple] = set()
    def_node_types: dict[tuple, str] = {}
    for nk, cap_names in node_key_to_captures.items():
        for cap_name in cap_names:
            if not cap_name.endswith(".def"):
                continue
            parts = cap_name.split(".")
            if parts:
                prefix = parts[0]
                def_key = f"{prefix}.def"
                if def_key in _CAPTURE_SCHEMA and _CAPTURE_SCHEMA[def_key][0] == "node":
                    def_node_keys.add(nk)
                    def_node_types[nk] = _CAPTURE_SCHEMA[def_key][1]

    # Precompute ancestor map: for each captured node, find the nearest
    # enclosing .def node. Single DFS pass over ALL AST nodes = O(n).
    ancestor_map: dict[tuple, Optional[tuple]] = {}
    _build_ancestor_map(root_node, def_node_keys, node_key_to_captures, ancestor_map)

    # -----------------------------------------------------------------------
    # Second pass: emit nodes with proper IDs (handling overloads)
    # -----------------------------------------------------------------------
    nodes: list[NodeRecord] = []
    node_key_to_id: dict[tuple, str] = {}
    emitted_base_ids: dict[str, int] = {}

    for nk in sorted(def_node_keys, key=lambda k: (k[1], k[2])):
        node = node_key_to_node.get(nk)
        if node is None:
            continue
        graph_type = def_node_types[nk]
        line = node.start_point[0] + 1
        base_id = f"{graph_type}:{file_path}:{line}"

        count = emitted_base_ids.get(base_id, 0)
        emitted_base_ids[base_id] = count + 1
        final_id = base_id if count == 0 else f"{base_id}#{count}"
        node_key_to_id[nk] = final_id

        # Extract name using ancestor_map for O(1) lookup
        name = _extract_name_for_node(nk, captures, graph_type, ancestor_map)

        # Extract metadata (annotations)
        metadata = _extract_annotations_for_node(nk, captures, ancestor_map)

        record = NodeRecord(
            id=final_id,
            type=graph_type,
            name=name,
            file_path=file_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            metadata=metadata,
        )
        nodes.append(record)

    # -----------------------------------------------------------------------
    # Third pass: emit non-contains edges (calls, imports, extends, implements)
    # -----------------------------------------------------------------------
    edges: list[EdgeRecord] = []

    for nk, cap_names in node_key_to_captures.items():
        node = node_key_to_node.get(nk)
        if node is None:
            continue

        # --- calls ---
        if _has_capture_prefix(cap_names, "call") and nk not in def_node_keys:
            source_nk = ancestor_map.get(nk)
            if source_nk is not None and source_nk in node_key_to_id:
                source_id = node_key_to_id[source_nk]
                target_name = _extract_call_target(cap_names, captures)
                if target_name:
                    target_id = f"UnresolvedCall:{target_name}"
                    edges.append(EdgeRecord(
                        source_id=source_id,
                        target_id=target_id,
                        relation="calls",
                        evidence_path=file_path,
                        evidence_line=node.start_point[0] + 1,
                        metadata={"confidence": 0.5, "raw_name": target_name},
                    ))

        # --- imports ---
        if _has_capture_prefix(cap_names, "import"):
            import_path = _extract_import_path(cap_names, captures)
            if import_path:
                source_id = f"Module:{file_path}"
                target_id = f"Import:{import_path}"
                edges.append(EdgeRecord(
                    source_id=source_id,
                    target_id=target_id,
                    relation="imports",
                    evidence_path=file_path,
                    evidence_line=node.start_point[0] + 1,
                    metadata={},
                ))

        # --- extends / implements ---
        for edge_type in ("extends", "implements"):
            if edge_type in cap_names and nk not in def_node_keys:
                source_nk = ancestor_map.get(nk)
                if source_nk is not None and source_nk in node_key_to_id:
                    source_id = node_key_to_id[source_nk]
                    target_name = _extract_edge_target(cap_names, captures, edge_type)
                    target_id = f"{edge_type.capitalize()}:{target_name}"
                    edges.append(EdgeRecord(
                        source_id=source_id,
                        target_id=target_id,
                        relation=edge_type,
                        evidence_path=file_path,
                        evidence_line=node.start_point[0] + 1,
                        metadata={},
                    ))

    # -----------------------------------------------------------------------
    # Fourth pass: emit contains edges for nesting
    # -----------------------------------------------------------------------
    contains_edges_set: set[tuple[str, str]] = set()

    for child_nk in def_node_keys:
        child_node = node_key_to_node.get(child_nk)
        if child_node is None:
            continue
        # Walk up the parent chain to find the nearest enclosing .def
        parent_node = child_node.parent
        while parent_node is not None:
            parent_nk = _node_key(parent_node)
            if parent_nk in def_node_keys:
                child_id = node_key_to_id.get(child_nk)
                parent_id = node_key_to_id.get(parent_nk)
                if child_id and parent_id:
                    edge_key = (parent_id, child_id)
                    if edge_key not in contains_edges_set:
                        contains_edges_set.add(edge_key)
                        edges.append(EdgeRecord(
                            source_id=parent_id,
                            target_id=child_id,
                            relation="contains",
                            evidence_path=file_path,
                            evidence_line=parent_node.start_point[0] + 1,
                            metadata={},
                        ))
                break
            parent_node = parent_node.parent

    return nodes, edges


def _has_capture_prefix(cap_names: list[str], prefix: str) -> bool:
    """Check if any capture name starts with the given prefix."""
    for cap_name in cap_names:
        if cap_name.startswith(prefix):
            return True
    return False


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _build_ancestor_map(
    node: Node,
    def_node_keys: set[tuple],
    captured_keys: dict[tuple, list[str]],
    ancestor_map: dict[tuple, Optional[tuple]],
) -> None:
    """Build ancestor map in a single DFS pass.
    
    For each captured node, find the nearest enclosing .def node ancestor.
    Uses iterative DFS to avoid stack overflow on large trees.
    """
    # Stack items: (node, current_def_ancestor_key_or_None)
    stack = [(node, None)]
    while stack:
        current, current_def = stack.pop()
        nk = _node_key(current)

        # Check if this node is a .def node
        new_def = current_def
        if nk in def_node_keys:
            new_def = nk

        # Only map captured nodes
        if nk in captured_keys:
            ancestor_map[nk] = new_def

        # Push children in reverse order for consistent traversal
        stack.extend((child, new_def) for child in reversed(current.children))


def _extract_name_for_node(
    def_node_key: tuple,
    captures: dict[str, list[Node]],
    graph_type: str,
    ancestor_map: dict[tuple, Optional[tuple]],
) -> str:
    """Extract the name for a specific .def node using ancestor_map."""
    prefix = graph_type.lower()
    name_key = f"{prefix}.name"
    if name_key in captures:
        for node in captures[name_key]:
            nk = _node_key(node)
            if ancestor_map.get(nk) == def_node_key:
                text = node.text.decode("utf-8", errors="replace").strip()
                if text:
                    return text

    # Fall back
    for cap_name, cap_nodes in captures.items():
        parts = cap_name.split(".")
        if parts and parts[0] == prefix:
            for node in cap_nodes:
                nk = _node_key(node)
                if ancestor_map.get(nk) == def_node_key:
                    text = node.text.decode("utf-8", errors="replace").strip()
                    if text:
                        return text

    return ""


def _extract_annotations_for_node(
    def_node_key: tuple,
    captures: dict[str, list[Node]],
    ancestor_map: dict[tuple, Optional[tuple]],
) -> dict:
    """Extract annotation metadata for a specific .def node."""
    annotations = []
    if "annotation.name" in captures:
        for node in captures["annotation.name"]:
            nk = _node_key(node)
            if ancestor_map.get(nk) == def_node_key:
                text = node.text.decode("utf-8", errors="replace").strip()
                if text:
                    annotations.append(text)
    return {"annotations": annotations} if annotations else {}


def _extract_call_target(
    cap_names: list[str],
    captures: dict[str, list[Node]],
) -> Optional[str]:
    """Extract the call target name from call captures."""
    if "call.target" in captures:
        for node in captures["call.target"]:
            text = node.text.decode("utf-8", errors="replace").strip()
            if text:
                return text
    for cap_name in cap_names:
        if cap_name.startswith("call."):
            for node in captures.get(cap_name, []):
                text = node.text.decode("utf-8", errors="replace").strip()
                if text:
                    return text
    return None


def _extract_import_path(
    cap_names: list[str],
    captures: dict[str, list[Node]],
) -> Optional[str]:
    """Extract the import path from import captures."""
    for cap_name in ("import.path", "import.site"):
        if cap_name in captures:
            for node in captures[cap_name]:
                text = node.text.decode("utf-8", errors="replace").strip()
                if text:
                    return text
    return None


def _extract_edge_target(
    cap_names: list[str],
    captures: dict[str, list[Node]],
    edge_type: str,
) -> str:
    """Extract the target name for extends/implements edges."""
    target_key = f"{edge_type}.target"
    if target_key in captures:
        for node in captures[target_key]:
            text = node.text.decode("utf-8", errors="replace").strip()
            if text:
                return text
    return ""
