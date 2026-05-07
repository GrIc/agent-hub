"""Heuristic FQN resolution for `calls` edges.

After AST extraction, `calls` edges have targets as simple names
(e.g. `foo`). The resolver rewrites these to fully-qualified names
using the import graph + intra-package references.

Design principles:
- Language-agnostic: works from the graph's import tuples, not from
  language-specific heuristics.
- Never invents nodes or edges. Only rewrites target_id and metadata.
- Unresolved identifiers get confidence=0.5 and unresolved=True; they
  are NEVER deleted.
- Resolved targets MUST be existing node IDs (satisfy FK constraints).

API:
    resolve_edges(store) -> ResolutionStats   # mutates store in place
    get_unresolved_edges(store)               # inspection helper
"""

import logging
from dataclasses import dataclass
from typing import Optional

from src.graph.store import GraphStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Record types
# ---------------------------------------------------------------------------

@dataclass
class ResolutionStats:
    """Return value from resolve_edges()."""
    resolved: int = 0
    unresolved: int = 0
    total: int = 0

    def to_dict(self) -> dict:
        return {"resolved": self.resolved, "unresolved": self.unresolved, "total": self.total}


# ---------------------------------------------------------------------------
# Build lookup maps
# ---------------------------------------------------------------------------

def _build_lookup_maps(store: GraphStore) -> tuple[
    dict[str, dict[str, list[str]]],   # per-file: short_name -> [node_id]
    dict[str, list[str]],              # global: short_name -> [node_id]
    dict[str, list[str]],              # package -> [file_path]
]:
    """Build all lookup maps needed for resolution.

    Returns:
        (short_name_map, global_name_map, package_map)
    """
    # Step 1: Collect all nodes grouped by file_path.
    nodes_by_file: dict[str, list[dict]] = {}
    for node in store.list_nodes(limit=100000):
        fp = node.get("file_path")
        if not fp:
            continue
        nodes_by_file.setdefault(fp, []).append(node)

    # Step 2: Collect all import edges grouped by source file.
    imports_by_file: dict[str, list[str]] = {}
    for edge in store.list_edges(relation="imports", limit=100000):
        src = edge["source_id"]
        tgt = edge["target_id"]
        if src.startswith("Module:"):
            file_path = src[len("Module:"):]
        else:
            file_path = edge.get("evidence_path", "")
        if tgt.startswith("Import:"):
            import_path = tgt[len("Import:"):]
            imports_by_file.setdefault(file_path, []).append(import_path)

    # Step 3: Build per-file and global short_name -> [node_id] maps.
    # Priority: actual node IDs (Class:, Method:, etc.) > import paths.
    short_name_map: dict[str, dict[str, list[str]]] = {}
    global_name_map: dict[str, list[str]] = {}

    for file_path, nodes in nodes_by_file.items():
        name_map: dict[str, list[str]] = {}

        def _add(name: str, fid: str) -> None:
            if not name or not fid:
                return
            if fid not in name_map.get(name, []):
                name_map.setdefault(name, []).append(fid)
            if fid not in global_name_map.get(name, []):
                global_name_map.setdefault(name, []).append(fid)

        # 3a. Intra-file declarations (Class, Method, Field, Module).
        for node in nodes:
            ntype = node.get("type", "")
            name = node.get("name")
            nid = node.get("id", "")
            if ntype in ("Class", "Method", "Field"):
                _add(name, nid)
            if ntype == "Module":
                _add(name, nid)

        # 3b. Imported symbols (only if no node ID candidate exists).
        for import_path in imports_by_file.get(file_path, []):
            parts = import_path.rsplit(".", 1)
            simple_name = parts[1] if len(parts) == 2 else import_path
            if simple_name and simple_name not in name_map:
                name_map[simple_name] = [import_path]

        if name_map:
            short_name_map[file_path] = name_map

    # Step 4: Build package -> [file_path] map.
    package_map: dict[str, list[str]] = {}
    for node in store.list_nodes(limit=100000):
        fp = node.get("file_path")
        if not fp:
            continue
        # Derive package: strip extension, then take directory portion.
        base = fp.rsplit(".", 1)[0] if "." in fp else fp
        package = base.rsplit("/", 1)[0] if "/" in base else "."
        package_map.setdefault(package, []).append(fp)

    return short_name_map, global_name_map, package_map


# ---------------------------------------------------------------------------
# Resolution logic
# ---------------------------------------------------------------------------

def _resolve_target(
    target_id: str,
    source_file: str,
    short_name_map: dict[str, dict[str, list[str]]],
    global_name_map: dict[str, list[str]],
    package_map: dict[str, list[str]],
) -> Optional[str]:
    """Attempt to resolve a call target to an existing node ID.

    Strategy (language-agnostic, priority order):
    1. If target is already a known node ID pattern, return as-is.
    2. Look up simple name in source file's short_name_map.
    3. Look up simple name in global_name_map (any file).
    4. Look up in same package files.
    5. Return None if unresolved.

    Args:
        target_id: Current target_id of the calls edge.
        source_file: file_path of the source node.
        short_name_map: Per-file short_name -> [node_id] map.
        global_name_map: Global short_name -> [node_id] map.
        package_map: Package -> [file_path] map.

    Returns:
        Resolved node ID, or None if unresolved.
    """
    # Skip already-resolved targets (known node ID patterns).
    if _is_node_id_pattern(target_id):
        return target_id

    # Extract simple name from target_id.
    simple_name = _extract_simple_name(target_id)
    if not simple_name:
        return None

    # Strategy 1: Source file's own map.
    if source_file in short_name_map:
        candidates = short_name_map[source_file].get(simple_name, [])
        node_id = _pick_node_id(candidates)
        if node_id:
            return node_id

    # Strategy 2: Global map (any file in the graph).
    global_candidates = global_name_map.get(simple_name, [])
    node_id = _pick_node_id(global_candidates)
    if node_id:
        return node_id

    # Strategy 3: Same package.
    source_package = _derive_package(source_file)
    if source_package:
        for pkg_file in package_map.get(source_package, []):
            if pkg_file == source_file:
                continue
            if pkg_file in short_name_map:
                candidates = short_name_map[pkg_file].get(simple_name, [])
                node_id = _pick_node_id(candidates)
                if node_id:
                    return node_id

    return None


def _is_node_id_pattern(target_id: str) -> bool:
    """Check if target_id matches a known node ID pattern."""
    return any(target_id.startswith(p) for p in
               ("Class:", "Method:", "Field:", "Module:", "Import:"))


def _extract_simple_name(target_id: str) -> str:
    """Extract the simple name from a target_id.

    Handles patterns like:
    - "UnresolvedCall:foo" -> "foo"
    - "foo" -> "foo"
    - "Class:Foo.java:42" -> "Foo" (already resolved)
    """
    if target_id.startswith("UnresolvedCall:"):
        return target_id[len("UnresolvedCall:"):]
    if ":" in target_id:
        return target_id.rsplit(":", 1)[-1]
    return target_id


def _pick_node_id(candidates: list[str]) -> Optional[str]:
    """Pick the first candidate that is an actual node ID.

    Returns None if only import paths are available — import paths
    are NOT valid edge targets because they won't satisfy FK constraints.
    """
    for c in candidates:
        if _is_node_id_pattern(c):
            return c
    # No valid node ID found — caller should mark as unresolved.
    return None


def _derive_package(file_path: str) -> str:
    """Derive the package name from a file path.

    e.g. "src/com/example/service/UserService.java" -> "src/com/example/service"
    """
    base = file_path.rsplit(".", 1)[0] if "." in file_path else file_path
    package = base.rsplit("/", 1)[0] if "/" in base else "."
    return package


def _derive_source_file(source_id: str, store: GraphStore) -> str:
    """Derive the file_path from a source node ID."""
    if source_id.startswith(("Class:", "Method:", "Field:")):
        # Pattern: "Type:file_path:line" — but file_path may contain colons.
        # Safe split: take everything between first and last colon.
        parts = source_id.split(":")
        if len(parts) >= 3:
            # Last part is line number, first is type, middle is file_path.
            return ":".join(parts[1:-1])
    if source_id.startswith("Module:"):
        return source_id[len("Module:"):]
    # Fallback: look up the node.
    node = store.get_node(source_id)
    return node.get("file_path", "") if node else ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_edges(store: GraphStore) -> ResolutionStats:
    """Resolve `calls` edge targets to node IDs using heuristic lookup.

    Mutates the store in place: rewrites target_id and updates metadata
    on each `calls` edge.

    Args:
        store: The GraphStore to resolve edges in.

    Returns:
        ResolutionStats with resolved/unresolved/total counts.
    """
    short_name_map, global_name_map, package_map = _build_lookup_maps(store)

    stats = ResolutionStats()
    calls_edges = store.list_edges(relation="calls", limit=100000)

    for edge in calls_edges:
        stats.total += 1
        source_id = edge["source_id"]
        target_id = edge["target_id"]
        metadata = edge.get("metadata", {})

        source_file = _derive_source_file(source_id, store)

        # Skip already-resolved targets.
        if _is_node_id_pattern(target_id):
            stats.resolved += 1
            continue

        # Attempt resolution.
        resolved_id = _resolve_target(
            target_id, source_file,
            short_name_map, global_name_map, package_map,
        )

        if resolved_id:
            store.upsert_edge(
                source_id=source_id,
                target_id=resolved_id,
                relation="calls",
                evidence_path=edge.get("evidence_path"),
                evidence_line=edge.get("evidence_line"),
                metadata={**metadata, "confidence": 1.0, "unresolved": False},
            )
            stats.resolved += 1
        else:
            store.upsert_edge(
                source_id=source_id,
                target_id=target_id,
                relation="calls",
                evidence_path=edge.get("evidence_path"),
                evidence_line=edge.get("evidence_line"),
                metadata={**metadata, "confidence": 0.5, "unresolved": True},
            )
            stats.unresolved += 1

    logger.info(
        "resolve_edges: total=%d resolved=%d unresolved=%d",
        stats.total, stats.resolved, stats.unresolved,
    )
    return stats


def apply_hub_node_dampening(store: GraphStore, threshold: float = 0.20, factor: float = 0.30) -> int:
    """Apply dampening to edges of hub nodes (nodes connected to >threshold of other nodes).

    Args:
        store: The GraphStore to modify in place.
        threshold: Fraction of total nodes above which a node is considered a hub (default: 0.20).
        factor: Multiplier to apply to hub node edge weights (default: 0.30).

    Returns:
        int: Number of edges modified.
    """
    # Get total node count
    total_nodes = store.stats()["nodes"]
    
    if total_nodes == 0:
        logger.info("apply_hub_node_dampening: graph empty, skipping")
        return 0
    
    hub_threshold = int(threshold * total_nodes)
    logger.info(
        "apply_hub_node_dampening: total_nodes=%d threshold=%d factor=%.2f",
        total_nodes, hub_threshold, factor,
    )
    
    # Collect all edges to inspect
    all_edges = list(store.list_edges(limit=1000000))
    modified_count = 0
    
    for edge in all_edges:
        source_id = edge["source_id"]
        # Count outgoing edges from source
        out_degree = sum(1 for e in all_edges if e["source_id"] == source_id)
        if out_degree > hub_threshold:
            logger.debug(
                "Node '%s' is a hub (%d edges, threshold: %d)",
                source_id, out_degree, hub_threshold
            )
            # Apply dampening to this edge
            metadata = edge.get("metadata", {})
            weight = metadata.get("weight", 1.0)
            dampened_weight = weight * factor
            store.upsert_edge(
                source_id=source_id,
                target_id=edge["target_id"],
                relation=edge["relation"],
                evidence_path=edge.get("evidence_path"),
                evidence_line=edge.get("evidence_line"),
                metadata={"weight": dampened_weight, **metadata},
            )
            modified_count += 1
            logger.debug(
                "  Dampened edge %s -> %s: %.2f -> %.2f",
                source_id, edge["target_id"], weight, dampened_weight
            )
    
    logger.info("apply_hub_node_dampening: modified %d edges", modified_count)
    return modified_count


def get_unresolved_edges(store: GraphStore) -> list[dict]:
    """Return all `calls` edges with unresolved=True in metadata.

    Args:
        store: The GraphStore to inspect.

    Returns:
        List of edge dicts with unresolved edges.
    """
    unresolved = []
    for edge in store.list_edges(relation="calls", limit=100000):
        metadata = edge.get("metadata", {})
        if metadata.get("unresolved", False):
            unresolved.append(edge)
    return unresolved
