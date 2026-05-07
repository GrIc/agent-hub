"""Schema validator for GraphRAG configuration.

Validates the ``graph:`` and ``knowledge_graph:`` sections of config.yaml
against the v2 schema defined in docs/roadmap/02_PHASE_GRAPHRAG_v2.md.

Usage::

    from src.graph.validator import validate_schema

    validate_schema(config)  # raises ValueError on inconsistency
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Allowed values (constants — not config-driven).
# ---------------------------------------------------------------------------

_ALLOWED_STORE_BACKENDS: frozenset[str] = frozenset({"sqlite"})

_ALLOWED_UNKNOWN_LANGUAGE_POLICIES: frozenset[str] = frozenset(
    {"topology_only", "skip"}
)

# Required top-level keys inside ``graph:``.
_GRAPH_REQUIRED_KEYS: frozenset[str] = frozenset({
    "store",
    "db_path",
    "queries_dir",
    "supported_languages",
    "extensions",
    "unknown_language_policy",
    "hub_dampening",
})

# Required keys inside ``graph.hub_dampening:``.
_HUB_DAMPENING_REQUIRED_KEYS: frozenset[str] = frozenset({
    "enabled",
    "threshold",
    "factor",
})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_schema(config: dict[str, Any], project_root: str | None = None) -> None:
    """Validate the GraphRAG schema in *config* and raise on inconsistency.

    Parameters
    ----------
    config:
        The full config dict (as returned by ``src.config.load_config``).
    project_root:
        Absolute path to the project root (used to resolve ``queries_dir``).
        If *None*, defaults to the directory containing this package's parent.

    Raises
    ------
    ValueError
        On any schema violation. The message describes the exact problem.
    """
    graph = config.get("graph")
    if graph is None:
        # GraphRAG is disabled or not configured — nothing to validate.
        return

    _validate_graph_section(graph, project_root)
    _validate_knowledge_graph(config.get("knowledge_graph"), graph)


# ---------------------------------------------------------------------------
# Internal validators
# ---------------------------------------------------------------------------

def _validate_graph_section(graph: dict[str, Any], project_root: str | None) -> None:
    """Check every required key and its type / allowed values."""

    # --- Required keys ---------------------------------------------------
    missing = _GRAPH_REQUIRED_KEYS - set(graph.keys())
    if missing:
        raise ValueError(
            f"graph section is missing required keys: {sorted(missing)}"
        )

    # --- store -----------------------------------------------------------
    store = graph["store"]
    if store not in _ALLOWED_STORE_BACKENDS:
        raise ValueError(
            f"graph.store must be one of {_ALLOWED_STORE_BACKENDS!r}, "
            f"got {store!r}"
        )

    # --- db_path ---------------------------------------------------------
    db_path = graph["db_path"]
    if not isinstance(db_path, str) or not db_path:
        raise ValueError("graph.db_path must be a non-empty string")

    # --- queries_dir -----------------------------------------------------
    queries_dir = graph["queries_dir"]
    if not isinstance(queries_dir, str) or not queries_dir:
        raise ValueError("graph.queries_dir must be a non-empty string")

    # Resolve the absolute path to queries_dir so we can check .scm files.
    if project_root is None:
        project_root = _resolve_project_root()
    queries_path = Path(project_root) / queries_dir

    # --- supported_languages ---------------------------------------------
    supported = graph["supported_languages"]
    if not isinstance(supported, list) or not supported:
        raise ValueError("graph.supported_languages must be a non-empty list")
    for lang in supported:
        if not isinstance(lang, str):
            raise ValueError(
                f"Each entry in graph.supported_languages must be a string, "
                f"got {lang!r}"
            )

    # Check that every listed language has a corresponding .scm file.
    for lang in supported:
        scm_file = queries_path / f"{lang}.scm"
        if not scm_file.exists():
            raise ValueError(
                f"graph.supported_languages includes {lang!r} but "
                f"{scm_file} does not exist. "
                f"Create the file or remove {lang!r} from supported_languages."
            )

    # --- extensions ------------------------------------------------------
    extensions = graph["extensions"]
    if not isinstance(extensions, dict):
        raise ValueError("graph.extensions must be a dict mapping extensions to language names")
    for ext, lang in extensions.items():
        if not isinstance(ext, str) or not ext.startswith("."):
            raise ValueError(
                f"graph.extensions keys must be dot-prefixed extensions, got {ext!r}"
            )
        if lang not in supported:
            raise ValueError(
                f"graph.extensions maps {ext!r} to language {lang!r}, "
                f"but {lang!r} is not in graph.supported_languages"
            )

    # --- unknown_language_policy -----------------------------------------
    policy = graph["unknown_language_policy"]
    if policy not in _ALLOWED_UNKNOWN_LANGUAGE_POLICIES:
        raise ValueError(
            f"graph.unknown_language_policy must be one of "
            f"{_ALLOWED_UNKNOWN_LANGUAGE_POLICIES!r}, got {policy!r}"
        )

    # --- hub_dampening ---------------------------------------------------
    hd = graph["hub_dampening"]
    if not isinstance(hd, dict):
        raise ValueError("graph.hub_dampening must be a dict")
    missing_hd = _HUB_DAMPENING_REQUIRED_KEYS - set(hd.keys())
    if missing_hd:
        raise ValueError(
            f"graph.hub_dampening is missing required keys: {sorted(missing_hd)}"
        )
    if not isinstance(hd["enabled"], bool):
        raise ValueError("graph.hub_dampening.enabled must be a boolean")
    if not isinstance(hd["threshold"], (int, float)):
        raise ValueError("graph.hub_dampening.threshold must be a number")
    if not isinstance(hd["factor"], (int, float)):
        raise ValueError("graph.hub_dampening.factor must be a number")


def _validate_knowledge_graph(
    kg: dict[str, Any] | None,
    graph: dict[str, Any],
) -> None:
    """Validate the ``knowledge_graph:`` section for relation consistency.

    This ensures that every ``allowed_relations`` value references a
    relation type that actually exists in ``relation_types``.
    """
    if kg is None:
        return

    node_types: list[str] = kg.get("node_types", [])
    relation_types: list[str] = kg.get("relation_types", [])

    if not isinstance(node_types, list):
        raise ValueError("knowledge_graph.node_types must be a list")
    if not isinstance(relation_types, list):
        raise ValueError("knowledge_graph.relation_types must be a list")

    relation_set: set[str] = set(relation_types)
    node_set: set[str] = set(node_types)

    allowed_relations: dict[str, list[str]] = kg.get("allowed_relations", {})
    if not isinstance(allowed_relations, dict):
        raise ValueError("knowledge_graph.allowed_relations must be a dict")

    for node_type, relations in allowed_relations.items():
        if node_type not in node_set and node_set:
            # Only warn if node_types is non-empty (strict mode).
            raise ValueError(
                f"knowledge_graph.allowed_relations references node type "
                f"{node_type!r} which is not in knowledge_graph.node_types"
            )
        if not isinstance(relations, list):
            raise ValueError(
                f"knowledge_graph.allowed_relations[{node_type!r}] must be a list"
            )
        for rel in relations:
            if relation_set and rel not in relation_set:
                raise ValueError(
                    f"knowledge_graph.allowed_relations[{node_type!r}] "
                    f"references relation {rel!r} which is not in "
                    f"knowledge_graph.relation_types"
                )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_project_root() -> str:
    """Heuristic: walk up from this file until we find config.yaml."""
    candidate = Path(__file__).resolve().parent.parent.parent
    while candidate != candidate.parent:
        if (candidate / "config.yaml").exists():
            return str(candidate)
        candidate = candidate.parent
    return str(Path.cwd())
