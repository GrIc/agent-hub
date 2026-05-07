"""Topology layer — filesystem + git graph extraction.

This module is fully language-agnostic. It works on every file regardless of
language — even files we can't parse (configs, docs, images).

Layers provided:
  1. Directory tree  →  Module contains Module / File edges.
  2. File nodes      →  one File node per indexed file.
  3. Co-change edges →  weighted File-File edges from git log history.

No tree-sitter, no LLM calls. Pure filesystem + optional git operations.

API:
    from src.graph.topology import (
        detect_workspace_type,
        emit_directory_tree,
        emit_file_nodes,
        emit_co_change_edges,
    )
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# File extensions that are never workspace roots (avoid recursing into DBs, etc.)
_SKIP_EXTENSIONS: set[str] = {".sqlite", ".db", ".graphdb"}

# Directories to skip during tree walk (mirrors config.yaml scanning.skip_dirs)
_SKIP_DIRS: set[str] = {
    "node_modules",
    "__pycache__",
    ".git",
    ".svn",
    ".hg",
    "dist",
    "build",
    ".next",
    "target",
    ".venv",
    "venv",
    ".idea",
    ".vscode",
    "vendor",
    ".vectordb",
    ".cache",
    ".tox",
    ".mypy_cache",
    ".ruff_cache",
}


# ---------------------------------------------------------------------------
# Data records
# ---------------------------------------------------------------------------

@dataclass
class TopologyNode:
    """A node emitted by the topology layer."""
    id: str
    type: str          # "Module" (directory) | "File"
    name: str
    file_path: str     # relative to workspace root (forward-slash)
    line_start: int = 0
    line_end: int = 0
    metadata: dict = field(default_factory=dict)


@dataclass
class TopologyEdge:
    """An edge emitted by the topology layer."""
    source_id: str
    target_id: str
    relation: str      # "contains" | "co_changes"
    evidence_path: Optional[str] = None
    evidence_line: Optional[int] = None
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Path normalisation (cross-platform)
# ---------------------------------------------------------------------------

def _norm_rel(path: Path) -> str:
    """Normalise a relative path to forward-slash form (cross-platform).

    On Windows, ``Path.as_posix()`` converts ``src\\main`` → ``src/main``.
    Git log always returns forward-slash paths, so we must match.
    """
    return path.as_posix()


# ---------------------------------------------------------------------------
# Workspace type detection
# ---------------------------------------------------------------------------

def detect_workspace_type(workspace: str) -> str:
    """Detect whether *workspace* is a git repository or a plain directory.

    Args:
        workspace: Absolute or relative path to the workspace root.

    Returns:
        "git" if a .git directory/file exists at the root, else "dir".
    """
    git_path = Path(workspace) / ".git"
    if git_path.exists():
        return "git"
    return "dir"


# ---------------------------------------------------------------------------
# Directory tree emission
# ---------------------------------------------------------------------------

def emit_directory_tree(
    workspace: str,
    skip_dirs: Optional[set[str]] = None,
) -> tuple[list[TopologyNode], list[TopologyEdge]]:
    """Walk the workspace directory tree and emit directory nodes + contains edges.

    This produces a hierarchical Module graph mirroring the filesystem layout.
    Every directory becomes a Module node; parent directories contain child
    directories via "contains" edges.

    Args:
        workspace: Absolute path to the workspace root.
        skip_dirs: Directories to skip (uses default if None).

    Returns:
        (nodes, edges) — directory Module nodes and "contains" edges.
    """
    skip = skip_dirs or _SKIP_DIRS
    workspace_path = Path(workspace).resolve()

    nodes: list[TopologyNode] = []
    edges: list[TopologyEdge] = []

    # Track seen directory IDs to avoid duplicates (hard links, symlinks).
    seen_dirs: set[str] = set()

    for dirpath, dirnames, _filenames in os.walk(workspace_path):
        # Prune skipped directories in-place to avoid recursion.
        dirnames[:] = sorted(
            [d for d in dirnames if d not in skip and not d.startswith(".")],
        )

        current_path = Path(dirpath)
        rel_path = current_path.relative_to(workspace_path)
        dir_id = _dir_to_module_id(rel_path)

        if dir_id not in seen_dirs:
            seen_dirs.add(dir_id)
            nodes.append(TopologyNode(
                id=dir_id,
                type="Module",
                name=rel_path.name or workspace_path.name,
                file_path=_norm_rel(rel_path),
                metadata={"is_workspace_root": _norm_rel(rel_path) == "."},
            ))

        # Parent → child contains edges.
        if rel_path != Path("."):
            parent_path = rel_path.parent
            parent_id = (
                _dir_to_module_id(parent_path)
                if parent_path != Path(".")
                else _dir_to_module_id(Path("."))
            )
            edges.append(TopologyEdge(
                source_id=parent_id,
                target_id=dir_id,
                relation="contains",
                evidence_path=_norm_rel(rel_path),
            ))

    logger.info(
        "emit_directory_tree(%s): %d directory nodes, %d contains edges",
        workspace, len(nodes), len(edges),
    )
    return nodes, edges


def _dir_to_module_id(rel_path: Path) -> str:
    """Convert a relative directory path to a stable Module ID.

    Examples:
        Path(".")           → "Module:."
        Path("src")         → "Module:src"
        Path("src/main/java") → "Module:src/main/java"
    """
    normed = _norm_rel(rel_path)
    if normed == ".":
        return "Module:."
    return "Module:" + normed


# ---------------------------------------------------------------------------
# File node emission
# ---------------------------------------------------------------------------

def emit_file_nodes(
    workspace: str,
    extensions: Optional[set[str]] = None,
    skip_dirs: Optional[set[str]] = None,
    max_file_size: int = 10_000_000,
) -> list[TopologyNode]:
    """Emit one File node per indexed file in the workspace.

    This works on every file regardless of language — even files we can't
    parse (configs, docs, images). For a file with no AST extraction, this
    is the only layer populated.

    Args:
        workspace: Absolute path to the workspace root.
        extensions: File extensions to include (None = all files).
        skip_dirs: Directories to skip (uses default if None).
        max_file_size: Skip files larger than this (bytes).

    Returns:
        List of File nodes.
    """
    skip = skip_dirs or _SKIP_DIRS
    workspace_path = Path(workspace).resolve()

    nodes: list[TopologyNode] = []
    count = 0

    for dirpath, _dirnames, filenames in os.walk(workspace_path):
        # We don't prune dirnames here because we need to walk all dirs
        # (the caller may want all files regardless of skip_dirs).
        # But we still skip hidden dirs.
        pass  # handled per-file below

    # Re-do with proper pruning.
    nodes = []
    count = 0
    for dirpath, dirnames, filenames in os.walk(workspace_path):
        dirnames[:] = sorted(
            [d for d in dirnames if d not in skip and not d.startswith(".")],
        )

        for fname in sorted(filenames):
            # Skip hidden files and workspace metadata.
            if fname.startswith("."):
                continue

            full_path = Path(dirpath) / fname
            rel_path = full_path.relative_to(workspace_path)
            normed = _norm_rel(rel_path)

            # Extension filter.
            if extensions is not None:
                if full_path.suffix.lower() not in extensions:
                    continue

            # Size filter.
            try:
                file_size = full_path.stat().st_size
            except OSError:
                continue
            if file_size > max_file_size:
                continue

            # Compute content hash for change detection.
            content_hash = _file_hash(full_path)

            node = TopologyNode(
                id="File:" + normed,
                type="File",
                name=fname,
                file_path=normed,
                metadata={
                    "size_bytes": file_size,
                    "content_hash": content_hash,
                    "extension": full_path.suffix,
                },
            )
            nodes.append(node)
            count += 1

    logger.info(
        "emit_file_nodes(%s): %d file nodes",
        workspace, count,
    )
    return nodes


def _file_hash(file_path: Path) -> str:
    """Compute SHA-256 hash of a file's content."""
    h = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except (OSError, IOError):
        return "error"
    return h.hexdigest()


def emit_file_contains_edges(
    workspace: str,
    file_nodes: list[TopologyNode],
) -> list[TopologyEdge]:
    """Emit File → parent Module "contains" edges for a list of File nodes.

    Args:
        workspace: Absolute path to the workspace root.
        file_nodes: File nodes returned by emit_file_nodes().

    Returns:
        List of "contains" edges from parent Module to File.
    """
    workspace_path = Path(workspace).resolve()
    edges: list[TopologyEdge] = []

    for node in file_nodes:
        rel_path = Path(node.file_path)
        parent_path = rel_path.parent
        parent_id = (
            _dir_to_module_id(parent_path)
            if parent_path != Path(".")
            else _dir_to_module_id(Path("."))
        )
        edges.append(TopologyEdge(
            source_id=parent_id,
            target_id=node.id,
            relation="contains",
            evidence_path=node.file_path,
        ))

    return edges


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _git_log_files(
    repo_path: str,
    since_days: int = 180,
) -> dict[str, list[str]]:
    """Get files changed per commit from git log.

    Args:
        repo_path: Path to the git repository root.
        since_days: Only consider commits from the last N days.

    Returns:
        Dict mapping commit hash → list of changed file paths (forward-slash).
    """
    since_dt = datetime.now(timezone.utc) - timedelta(days=since_days)
    since_ts = int(since_dt.timestamp())

    try:
        result = subprocess.run(
            [
                "git", "log", "--format=%H",
                f"--since={since_ts}",
                "--name-only",
                "--diff-filter=ACDMR",  # Added, Copied, Modified, Renamed
            ],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            logger.warning("git log failed: %s", result.stderr[:500])
            return {}
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        logger.warning("git log error: %s", exc)
        return {}

    commits: dict[str, list[str]] = {}
    current_hash: Optional[str] = None

    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # Check if this is a commit hash (40 hex chars).
        if len(line) == 40 and all(c in "0123456789abcdef" for c in line):
            current_hash = line
            commits[current_hash] = []
        elif current_hash is not None:
            # Normalise to forward-slash (git always returns forward-slash,
            # but be defensive on Windows).
            commits[current_hash].append(line.replace("\\", "/"))

    return commits


# ---------------------------------------------------------------------------
# Co-change edge emission
# ---------------------------------------------------------------------------

def emit_co_change_edges(
    repo_path: str,
    since_days: int = 180,
) -> list[TopologyEdge]:
    """Compute co-change edges from git log history.

    Two files that are changed in the same commit get a co_changes edge.
    The weight (metadata["weight"]) is the number of shared commits.

    Only considers files that exist as File nodes (i.e., are in the workspace).

    Args:
        repo_path: Path to the git repository root.
        since_days: Only consider commits from the last N days.

    Returns:
        List of weighted "co_changes" edges.
    """
    commits = _git_log_files(repo_path, since_days=since_days)
    if not commits:
        logger.info("emit_co_change_edges: no git history found")
        return []

    # Build a file → set of commit hashes mapping.
    file_commits: dict[str, set[str]] = {}
    for commit_hash, files in commits.items():
        for f in files:
            if f not in file_commits:
                file_commits[f] = set()
            file_commits[f].add(commit_hash)

    # Compute co-change pairs using a dict to accumulate weights.
    co_change_weights: dict[tuple[str, str], int] = {}

    for commit_hash, files in commits.items():
        if len(files) < 2:
            continue
        # Sort for deterministic edge ordering.
        sorted_files = sorted(files)
        for i in range(len(sorted_files)):
            for j in range(i + 1, len(sorted_files)):
                f1, f2 = sorted_files[i], sorted_files[j]
                key = (f1, f2)
                co_change_weights[key] = co_change_weights.get(key, 0) + 1

    # Convert to edges. Only include edges with weight >= 2 to reduce noise.
    edges: list[TopologyEdge] = []
    min_weight = 2

    for (f1, f2), weight in sorted(co_change_weights.items(), key=lambda x: -x[1]):
        if weight < min_weight:
            break
        edge = TopologyEdge(
            source_id="File:" + f1,
            target_id="File:" + f2,
            relation="co_changes",
            evidence_path=f1,
            metadata={
                "weight": weight,
                "shared_commits": weight,
                "since_days": since_days,
            },
        )
        edges.append(edge)

    logger.info(
        "emit_co_change_edges(%s, %d days): %d edges (min_weight=%d)",
        repo_path, since_days, len(edges), min_weight,
    )
    return edges


# ---------------------------------------------------------------------------
# Blame helper (informational, not stored as edges by default)
# ---------------------------------------------------------------------------

def emit_git_blame(
    repo_path: str,
    file_path: str,
) -> dict:
    """Run git blame on a single file and return structured data.

    Args:
        repo_path: Path to the git repository root.
        file_path: Relative path to the file (forward-slash).

    Returns:
        Dict with blame info:
            {"commit": str, "author": str, "line": int, "timestamp": str}
        Empty dict on failure.
    """
    try:
        result = subprocess.run(
            ["git", "blame", "--porcelain", file_path],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return {}
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return {}

    blame_lines: list[dict] = []
    current_commit: Optional[str] = None
    current_author: Optional[str] = None
    current_line_num: Optional[int] = None

    for line in result.stdout.split("\n"):
        parts = line.split()
        if len(parts) >= 1:
            # Full commit hash line.
            if len(parts[0]) == 40 and all(c in "0123456789abcdef" for c in parts[0]):
                current_commit = parts[0]
                current_line_num = int(parts[1]) if len(parts) > 1 else None
                continue
            # Author line.
            if line.startswith("author "):
                current_author = line[len("author "):]
                continue
            # AuthorTime line.
            if line.startswith("author-time "):
                continue
            # Original line number.
            if line.startswith("\t"):
                continue

        if current_commit and current_author and current_line_num is not None:
            blame_lines.append({
                "commit": current_commit,
                "author": current_author,
                "line": current_line_num,
            })
            current_commit = None
            current_author = None
            current_line_num = None

    return {"file": file_path, "blame_lines": blame_lines}


# ---------------------------------------------------------------------------
# Bulk topology builder (convenience)
# ---------------------------------------------------------------------------

def build_topology(
    workspace: str,
    db_path: str = ".graphdb/graph.sqlite",
    since_days: int = 180,
    extensions: Optional[set[str]] = None,
    skip_dirs: Optional[set[str]] = None,
) -> dict:
    """Build the full topology layer and write to the graph store.

    This is a convenience function that runs all topology passes and
    writes the results to the SQLite graph store.

    Args:
        workspace: Absolute path to the workspace root.
        db_path: Path to the SQLite graph database.
        since_days: Git co-change window.
        extensions: File extensions to index (None = all).
        skip_dirs: Directories to skip.

    Returns:
        Summary dict with counts.
    """
    from src.graph.store import GraphStore

    store = GraphStore(db_path)
    workspace_type = detect_workspace_type(workspace)

    # Pass 1: directory tree.
    dir_nodes, dir_edges = emit_directory_tree(workspace, skip_dirs=skip_dirs)
    for node in dir_nodes:
        store.upsert_node(
            id=node.id,
            type=node.type,
            name=node.name,
            file_path=node.file_path,
            line_start=node.line_start,
            line_end=node.line_end,
            metadata=node.metadata,
        )
    for edge in dir_edges:
        store.upsert_edge(
            source_id=edge.source_id,
            target_id=edge.target_id,
            relation=edge.relation,
            evidence_path=edge.evidence_path,
            evidence_line=edge.evidence_line,
            metadata=edge.metadata,
        )

    # Pass 2: file nodes + contains edges.
    file_nodes = emit_file_nodes(
        workspace,
        extensions=extensions,
        skip_dirs=skip_dirs,
    )
    for node in file_nodes:
        store.upsert_node(
            id=node.id,
            type=node.type,
            name=node.name,
            file_path=node.file_path,
            line_start=node.line_start,
            line_end=node.line_end,
            metadata=node.metadata,
        )

    file_edges = emit_file_contains_edges(workspace, file_nodes)
    for edge in file_edges:
        store.upsert_edge(
            source_id=edge.source_id,
            target_id=edge.target_id,
            relation=edge.relation,
            evidence_path=edge.evidence_path,
            evidence_line=edge.evidence_line,
            metadata=edge.metadata,
        )

    # Pass 3: co-change edges (git only).
    # Only emit edges whose endpoints are both existing File nodes.
    # Git log may reference deleted / hidden files that have no File node.
    known_file_ids = {n.id for n in file_nodes}
    co_change_edges: list[TopologyEdge] = []
    if workspace_type == "git":
        raw_edges = emit_co_change_edges(workspace, since_days=since_days)
        for edge in raw_edges:
            if edge.source_id in known_file_ids and edge.target_id in known_file_ids:
                co_change_edges.append(edge)
                store.upsert_edge(
                    source_id=edge.source_id,
                    target_id=edge.target_id,
                    relation=edge.relation,
                    evidence_path=edge.evidence_path,
                    evidence_line=edge.evidence_line,
                    metadata=edge.metadata,
                )
            else:
                logger.debug(
                    "Skipping co-change edge %s → %s (file node not present)",
                    edge.source_id, edge.target_id,
                )

    stats = store.stats()
    logger.info(
        "build_topology complete: %d dir nodes, %d file nodes, %d co-change edges",
        len(dir_nodes), len(file_nodes), len(co_change_edges),
    )

    return {
        "workspace_type": workspace_type,
        "directory_nodes": len(dir_nodes),
        "directory_edges": len(dir_edges),
        "file_nodes": len(file_nodes),
        "file_contains_edges": len(file_edges),
        "co_change_edges": len(co_change_edges),
        "total_nodes": stats["node_count"],
        "total_edges": stats["edge_count"],
    }
