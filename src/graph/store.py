"""SQLite-backed graph store for GraphRAG (Phase 2).

Provides a queryable, incremental graph store with:
- Nodes (Module, Class, Method, Field, File, etc.)
- Edges (contains, calls, imports, extends, implements, co_changes, etc.)
- File-state tracking for incremental updates
- Meta table for run metadata

Schema supports ~1M nodes on SQLite. All metadata stored as JSON.
No pickle, no Cypher-like DSL — only typed methods.
"""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
-- Nodes: one row per AST / topology entity.
CREATE TABLE IF NOT EXISTS nodes (
    id            TEXT PRIMARY KEY,
    type          TEXT NOT NULL,          -- Module | Class | Method | Field | File
    name          TEXT,                   -- human-readable name
    file_path     TEXT,                   -- source file (nullable for topology nodes)
    line_start    INTEGER,
    line_end      INTEGER,
    metadata      TEXT DEFAULT '{}',      -- JSON blob
    created_at    TEXT DEFAULT (datetime('now')),
    updated_at    TEXT DEFAULT (datetime('now'))
);

-- Edges: directed relationships between nodes.
CREATE TABLE IF NOT EXISTS edges (
    source_id     TEXT NOT NULL,
    target_id     TEXT NOT NULL,
    relation      TEXT NOT NULL,          -- contains | calls | imports | extends | implements | co_changes
    evidence_path TEXT,                   -- source file where edge was observed
    evidence_line INTEGER,
    metadata      TEXT DEFAULT '{}',      -- JSON blob (confidence, weight, etc.)
    created_at    TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (source_id, target_id, relation),
    FOREIGN KEY (source_id) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (target_id) REFERENCES nodes(id) ON DELETE CASCADE
);

-- file_state: tracks which files have been ingested and when.
CREATE TABLE IF NOT EXISTS file_state (
    file_path     TEXT PRIMARY KEY,
    content_hash  TEXT NOT NULL,          -- sha256 of source content
    node_count    INTEGER DEFAULT 0,
    edge_count    INTEGER DEFAULT 0,
    ingested_at   TEXT DEFAULT (datetime('now'))
);

-- meta: key-value store for run-level metadata.
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
CREATE INDEX IF NOT EXISTS idx_nodes_file_path ON nodes(file_path);
CREATE INDEX IF NOT EXISTS idx_nodes_type_file ON nodes(type, file_path);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_relation ON edges(relation);
CREATE INDEX IF NOT EXISTS idx_edges_source_relation ON edges(source_id, relation);
CREATE INDEX IF NOT EXISTS idx_edges_target_relation ON edges(target_id, relation);
CREATE INDEX IF NOT EXISTS idx_file_state_hash ON file_state(content_hash);
"""


# ---------------------------------------------------------------------------
# GraphStore
# ---------------------------------------------------------------------------

class GraphStore:
    """SQLite-backed graph store with incremental updates.

    Usage:
        store = GraphStore("my_graph.db")
        store.upsert_node(id="Class:Foo.java:42", type="Class", name="Foo",
                          file_path="src/Foo.java", line_start=42, line_end=55)
        store.upsert_edge(source_id="Class:Foo.java:42", target_id="Class:Bar.java:10",
                          relation="extends", evidence_path="src/Foo.java", evidence_line=42)
        stats = store.stats()
    """

    def __init__(self, db_path: str = ".graphdb/graph.sqlite", foreign_keys: bool = True):
        """Open (or create) the SQLite database.

        Args:
            db_path: Path to the SQLite database file.
            foreign_keys: Whether to enable foreign key constraints (default True).
        """
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        if foreign_keys:
            self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA_SQL)
        self.conn.executescript(INDEX_SQL)
        self.conn.commit()
        logger.info("GraphStore opened: %s", db_path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _serialize_metadata(self, metadata: Optional[dict]) -> str:
        """Serialize metadata dict to JSON string. Returns '{}' for None."""
        if metadata is None:
            return "{}"
        return json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))

    def _deserialize_metadata(self, raw: Optional[str]) -> dict:
        """Deserialize JSON metadata string to dict."""
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}

    def _build_node_row(self, node: dict) -> tuple:
        """Build a parameter tuple from a node dict for INSERT/UPDATE."""
        return (
            node["id"],
            node.get("type", "Unknown"),
            node.get("name"),
            node.get("file_path"),
            node.get("line_start"),
            node.get("line_end"),
            self._serialize_metadata(node.get("metadata")),
        )

    # ------------------------------------------------------------------
    # Node operations
    # ------------------------------------------------------------------

    def upsert_node(self, id: str, type: str, name: Optional[str] = None,
                    file_path: Optional[str] = None, line_start: Optional[int] = None,
                    line_end: Optional[int] = None, metadata: Optional[dict] = None) -> None:
        """Insert or update a node. Idempotent: re-upserting the same id
        overwrites all fields with the new values.

        Args:
            id: Unique node identifier.
            type: Node type (Module, Class, Method, Field, File, etc.).
            name: Human-readable name.
            file_path: Source file path (nullable).
            line_start: Starting line number (1-based, nullable).
            line_end: Ending line number (1-based, nullable).
            metadata: Arbitrary JSON-serializable dict.
        """
        self.conn.execute(
            """
            INSERT INTO nodes (id, type, name, file_path, line_start, line_end, metadata, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(id) DO UPDATE SET
                type = excluded.type,
                name = excluded.name,
                file_path = excluded.file_path,
                line_start = excluded.line_start,
                line_end = excluded.line_end,
                metadata = excluded.metadata,
                updated_at = datetime('now')
            """,
            (id, type, name, file_path, line_start, line_end,
             self._serialize_metadata(metadata)),
        )
        self.conn.commit()

    def get_node(self, id: str) -> Optional[dict]:
        """Retrieve a single node by id, or None."""
        row = self.conn.execute(
            "SELECT id, type, name, file_path, line_start, line_end, metadata FROM nodes WHERE id = ?",
            (id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "type": row["type"],
            "name": row["name"],
            "file_path": row["file_path"],
            "line_start": row["line_start"],
            "line_end": row["line_end"],
            "metadata": self._deserialize_metadata(row["metadata"]),
        }

    def delete_node(self, id: str) -> bool:
        """Delete a node by id. Returns True if a row was removed."""
        cursor = self.conn.execute("DELETE FROM nodes WHERE id = ?", (id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def list_nodes(self, node_type: Optional[str] = None,
                   file_path: Optional[str] = None,
                   limit: int = 1000, offset: int = 0) -> list[dict]:
        """List nodes with optional filters.

        Args:
            node_type: Filter by node type.
            file_path: Filter by file path (exact match).
            limit: Max rows to return.
            offset: Row offset for pagination.

        Returns:
            List of node dicts.
        """
        conditions: list[str] = []
        params: list[Any] = []

        if node_type:
            conditions.append("type = ?")
            params.append(node_type)
        if file_path:
            conditions.append("file_path = ?")
            params.append(file_path)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        query = f"""
            SELECT id, type, name, file_path, line_start, line_end, metadata
            FROM nodes{where}
            ORDER BY id
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        rows = self.conn.execute(query, params).fetchall()
        return [
            {
                "id": r["id"],
                "type": r["type"],
                "name": r["name"],
                "file_path": r["file_path"],
                "line_start": r["line_start"],
                "line_end": r["line_end"],
                "metadata": self._deserialize_metadata(r["metadata"]),
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Edge operations
    # ------------------------------------------------------------------

    def upsert_edge(self, source_id: str, target_id: str, relation: str,
                    evidence_path: Optional[str] = None,
                    evidence_line: Optional[int] = None,
                    metadata: Optional[dict] = None) -> None:
        """Insert or update an edge. Composite primary key is
        (source_id, target_id, relation).

        Args:
            source_id: Source node id.
            target_id: Target node id.
            relation: Edge relation type.
            evidence_path: Source file where edge was observed.
            evidence_line: Line number in the source file.
            metadata: Arbitrary JSON-serializable dict.
        """
        self.conn.execute(
            """
            INSERT INTO edges (source_id, target_id, relation, evidence_path, evidence_line, metadata)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id, target_id, relation) DO UPDATE SET
                evidence_path = excluded.evidence_path,
                evidence_line = excluded.evidence_line,
                metadata = excluded.metadata
            """,
            (source_id, target_id, relation, evidence_path, evidence_line,
             self._serialize_metadata(metadata)),
        )
        self.conn.commit()

    def get_edge(self, source_id: str, target_id: str,
                 relation: str) -> Optional[dict]:
        """Retrieve a single edge, or None."""
        row = self.conn.execute(
            """
            SELECT source_id, target_id, relation, evidence_path, evidence_line, metadata
            FROM edges
            WHERE source_id = ? AND target_id = ? AND relation = ?
            """,
            (source_id, target_id, relation),
        ).fetchone()
        if row is None:
            return None
        return {
            "source_id": row["source_id"],
            "target_id": row["target_id"],
            "relation": row["relation"],
            "evidence_path": row["evidence_path"],
            "evidence_line": row["evidence_line"],
            "metadata": self._deserialize_metadata(row["metadata"]),
        }

    def delete_edge(self, source_id: str, target_id: str,
                    relation: str) -> bool:
        """Delete an edge. Returns True if a row was removed."""
        cursor = self.conn.execute(
            "DELETE FROM edges WHERE source_id = ? AND target_id = ? AND relation = ?",
            (source_id, target_id, relation),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def list_edges(self, source_id: Optional[str] = None,
                   target_id: Optional[str] = None,
                   relation: Optional[str] = None,
                   limit: int = 10000) -> list[dict]:
        """List edges with optional filters.

        Args:
            source_id: Filter by source node id.
            target_id: Filter by target node id.
            relation: Filter by edge relation.
            limit: Max rows to return.

        Returns:
            List of edge dicts.
        """
        conditions: list[str] = []
        params: list[Any] = []

        if source_id:
            conditions.append("source_id = ?")
            params.append(source_id)
        if target_id:
            conditions.append("target_id = ?")
            params.append(target_id)
        if relation:
            conditions.append("relation = ?")
            params.append(relation)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        query = f"""
            SELECT source_id, target_id, relation, evidence_path, evidence_line, metadata
            FROM edges{where}
            LIMIT ?
        """
        params.append(limit)

        rows = self.conn.execute(query, params).fetchall()
        return [
            {
                "source_id": r["source_id"],
                "target_id": r["target_id"],
                "relation": r["relation"],
                "evidence_path": r["evidence_path"],
                "evidence_line": r["evidence_line"],
                "metadata": self._deserialize_metadata(r["metadata"]),
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Incremental updates
    # ------------------------------------------------------------------

    def delete_for_file(self, file_path: str) -> dict:
        """Remove all nodes whose file_path matches AND any edges referencing them.

        This is the primary incremental update mechanism: before re-extracting
        a changed file, call delete_for_file() to clean up old data.

        Args:
            file_path: Source file path to remove.

        Returns:
            Dict with counts: {"nodes": N, "edges": M}.
        """
        # Step 1: Count nodes to be removed.
        node_count = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM nodes WHERE file_path = ?",
            (file_path,),
        ).fetchone()["cnt"]

        # Step 2: Collect node ids that will be removed (their file_path matches).
        removed_node_ids = self.conn.execute(
            "SELECT id FROM nodes WHERE file_path = ?",
            (file_path,),
        ).fetchall()
        removed_ids = [r["id"] for r in removed_node_ids]

        # Step 3: Count ALL edges that will be removed BEFORE any deletion.
        # These are edges where source_id or target_id is a removed node,
        # OR edges where evidence_path matches the file.
        if removed_ids:
            placeholders = ",".join("?" for _ in removed_ids)
            total_edge_count = self.conn.execute(
                f"""
                SELECT COUNT(*) as cnt FROM edges
                WHERE evidence_path = ?
                   OR source_id IN ({placeholders})
                   OR target_id IN ({placeholders})
                """,
                [file_path] + removed_ids + removed_ids,
            ).fetchone()["cnt"]
        else:
            total_edge_count = self.conn.execute(
                "SELECT COUNT(*) as cnt FROM edges WHERE evidence_path = ?",
                (file_path,),
            ).fetchone()["cnt"]

        # Step 4: Delete edges referencing removed nodes.
        if removed_ids:
            placeholders = ",".join("?" for _ in removed_ids)
            self.conn.execute(
                f"DELETE FROM edges WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})",
                removed_ids + removed_ids,
            )

        # Step 5: Delete edges with evidence_path matching the file
        # (these may reference nodes not in the removed set).
        self.conn.execute(
            "DELETE FROM edges WHERE evidence_path = ?",
            (file_path,),
        )

        # Step 6: Delete nodes from the file.
        self.conn.execute("DELETE FROM nodes WHERE file_path = ?", (file_path,))

        # Step 7: Update file_state.
        self.conn.execute("DELETE FROM file_state WHERE file_path = ?", (file_path,))

        self.conn.commit()

        logger.info(
            "delete_for_file('%s'): %d nodes, %d edges removed",
            file_path, node_count, total_edge_count,
        )
        return {"nodes": node_count, "edges": total_edge_count}

    def record_file_state(self, file_path: str, content_hash: str,
                          node_count: int = 0, edge_count: int = 0) -> None:
        """Record or update the ingestion state for a file.

        Args:
            file_path: Source file path.
            content_hash: SHA-256 hash of the file content.
            node_count: Number of nodes extracted from this file.
            edge_count: Number of edges extracted from this file.
        """
        self.conn.execute(
            """
            INSERT INTO file_state (file_path, content_hash, node_count, edge_count, ingested_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(file_path) DO UPDATE SET
                content_hash = excluded.content_hash,
                node_count = excluded.node_count,
                edge_count = excluded.edge_count,
                ingested_at = datetime('now')
            """,
            (file_path, content_hash, node_count, edge_count),
        )
        self.conn.commit()

    def get_file_state(self, file_path: str) -> Optional[dict]:
        """Retrieve file ingestion state, or None."""
        row = self.conn.execute(
            "SELECT file_path, content_hash, node_count, edge_count, ingested_at FROM file_state WHERE file_path = ?",
            (file_path,),
        ).fetchone()
        if row is None:
            return None
        return {
            "file_path": row["file_path"],
            "content_hash": row["content_hash"],
            "node_count": row["node_count"],
            "edge_count": row["edge_count"],
            "ingested_at": row["ingested_at"],
        }

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_callers(self, node_id: str) -> list[dict]:
        """Find all nodes that call the given node.

        Args:
            node_id: Target node id.

        Returns:
            List of caller node dicts (with edge metadata).
        """
        rows = self.conn.execute(
            """
            SELECT n.id, n.type, n.name, n.file_path, n.line_start, n.line_end,
                   n.metadata,
                   e.evidence_path, e.evidence_line, e.metadata AS edge_metadata
            FROM edges e
            JOIN nodes n ON e.source_id = n.id
            WHERE e.target_id = ? AND e.relation = 'calls'
            ORDER BY n.id
            """,
            (node_id,),
        ).fetchall()
        return [
            {
                "node": {
                    "id": r["id"],
                    "type": r["type"],
                    "name": r["name"],
                    "file_path": r["file_path"],
                    "line_start": r["line_start"],
                    "line_end": r["line_end"],
                    "metadata": self._deserialize_metadata(r["metadata"]),
                },
                "edge": {
                    "evidence_path": r["evidence_path"],
                    "evidence_line": r["evidence_line"],
                    "metadata": self._deserialize_metadata(r["edge_metadata"]),
                },
            }
            for r in rows
        ]

    def get_callees(self, node_id: str) -> list[dict]:
        """Find all nodes called by the given node.

        Args:
            node_id: Source node id.

        Returns:
            List of callee node dicts (with edge metadata).
        """
        rows = self.conn.execute(
            """
            SELECT n.id, n.type, n.name, n.file_path, n.line_start, n.line_end,
                   n.metadata,
                   e.evidence_path, e.evidence_line, e.metadata AS edge_metadata
            FROM edges e
            JOIN nodes n ON e.target_id = n.id
            WHERE e.source_id = ? AND e.relation = 'calls'
            ORDER BY n.id
            """,
            (node_id,),
        ).fetchall()
        return [
            {
                "node": {
                    "id": r["id"],
                    "type": r["type"],
                    "name": r["name"],
                    "file_path": r["file_path"],
                    "line_start": r["line_start"],
                    "line_end": r["line_end"],
                    "metadata": self._deserialize_metadata(r["metadata"]),
                },
                "edge": {
                    "evidence_path": r["evidence_path"],
                    "evidence_line": r["evidence_line"],
                    "metadata": self._deserialize_metadata(r["edge_metadata"]),
                },
            }
            for r in rows
        ]

    def get_neighbors(self, node_id: str) -> dict:
        """Get all incoming and outgoing edges for a node.

        Args:
            node_id: Node id.

        Returns:
            Dict with 'incoming' and 'outgoing' lists.
        """
        incoming = self.conn.execute(
            """
            SELECT e.source_id, e.relation AS incoming_relation,
                   n.name AS source_name, n.type AS source_type
            FROM edges e
            JOIN nodes n ON e.source_id = n.id
            WHERE e.target_id = ?
            ORDER BY e.relation, e.source_id
            """,
            (node_id,),
        ).fetchall()

        outgoing = self.conn.execute(
            """
            SELECT e.target_id, e.relation AS outgoing_relation,
                   n.name AS target_name, n.type AS target_type
            FROM edges e
            JOIN nodes n ON e.target_id = n.id
            WHERE e.source_id = ?
            ORDER BY e.relation, e.target_id
            """,
            (node_id,),
        ).fetchall()

        return {
            "incoming": [
                {"source_id": r["source_id"], "relation": r["incoming_relation"],
                 "source_name": r["source_name"], "source_type": r["source_type"]}
                for r in incoming
            ],
            "outgoing": [
                {"target_id": r["target_id"], "relation": r["outgoing_relation"],
                 "target_name": r["target_name"], "target_type": r["target_type"]}
                for r in outgoing
            ],
        }

    def shortest_path(self, source_id: str, target_id: str) -> Optional[list[str]]:
        """Find the shortest path between two nodes using NetworkX.

        Uses BFS via NetworkX. The subgraph is capped at 10k nodes to
        prevent memory issues.

        Args:
            source_id: Source node id.
            target_id: Target node id.

        Returns:
            List of node ids forming the shortest path, or None if no path.
        """
        try:
            import networkx as nx
        except ImportError:
            logger.error("NetworkX not installed; install with: pip install networkx")
            return None

        # Build a subgraph from the database (capped at 10k nodes).
        all_nodes = self.conn.execute(
            "SELECT id FROM nodes LIMIT 10000"
        ).fetchall()
        node_ids = [r["id"] for r in all_nodes]

        G = nx.DiGraph()
        G.add_nodes_from(node_ids)

        rows = self.conn.execute(
            "SELECT source_id, target_id FROM edges WHERE source_id IN (%s)"
            % ",".join("?" for _ in node_ids),
            node_ids,
        ).fetchall()

        for row in rows:
            G.add_edge(row["source_id"], row["target_id"])

        try:
            path = nx.shortest_path(G, source=source_id, target=target_id)
            return path
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

    def preview_impact(self, node_id: str, max_nodes: int = 10000) -> dict:
        """Preview the impact of deleting a node: what would be affected.

        Uses NetworkX subgraph analysis. The subgraph is capped at max_nodes.

        Args:
            node_id: Node id to analyze.
            max_nodes: Maximum nodes in the subgraph.

        Returns:
            Dict with:
                - 'direct_callers': nodes that call this node
                - 'direct_callees': nodes this node calls
                - 'transitive_reachable': count of nodes reachable from this node
                - 'transitive_dependents': count of nodes that can reach this node
                - 'is_hub': True if degree > threshold
        """
        try:
            import networkx as nx
        except ImportError:
            logger.error("NetworkX not installed; install with: pip install networkx")
            return {
                "direct_callers": [],
                "direct_callees": [],
                "transitive_reachable": 0,
                "transitive_dependents": 0,
                "is_hub": False,
            }

        # Build subgraph centered on node_id.
        all_nodes = self.conn.execute(
            "SELECT id FROM nodes LIMIT ?", (max_nodes,)
        ).fetchall()
        node_ids = [r["id"] for r in all_nodes]

        G = nx.DiGraph()
        G.add_nodes_from(node_ids)

        rows = self.conn.execute(
            "SELECT source_id, target_id FROM edges WHERE source_id IN (%s)"
            % ",".join("?" for _ in node_ids),
            node_ids,
        ).fetchall()

        for row in rows:
            G.add_edge(row["source_id"], row["target_id"])

        # Direct callers (incoming 'calls' edges).
        direct_callers = [
            r["source_id"]
            for r in self.conn.execute(
                """
                SELECT e.source_id
                FROM edges e
                WHERE e.target_id = ? AND e.relation = 'calls'
                """,
                (node_id,),
            ).fetchall()
        ]

        # Direct callees (outgoing 'calls' edges).
        direct_callees = [
            r["target_id"]
            for r in self.conn.execute(
                """
                SELECT e.target_id
                FROM edges e
                WHERE e.source_id = ? AND e.relation = 'calls'
                """,
                (node_id,),
            ).fetchall()
        ]

        # Transitive reachability (nodes reachable FROM this node).
        transitive_reachable = 0
        if node_id in G:
            reachable = nx.descendants(G, node_id)
            transitive_reachable = len(reachable)

        # Transitive dependents (nodes that can reach this node).
        transitive_dependents = 0
        if node_id in G:
            # Reverse graph: who can reach this node?
            reverse = G.reverse()
            dependents = nx.descendants(reverse, node_id)
            transitive_dependents = len(dependents)

        # Hub detection: high total degree.
        total_degree = G.degree(node_id) if node_id in G else 0
        is_hub = total_degree > 20  # configurable threshold later

        return {
            "direct_callers": direct_callers,
            "direct_callees": direct_callees,
            "transitive_reachable": transitive_reachable,
            "transitive_dependents": transitive_dependents,
            "is_hub": is_hub,
            "total_degree": total_degree,
        }

    def find_hub_modules(self, threshold: int = 50) -> list[dict]:
        """Find modules (or classes) with unusually high connection counts.

        A hub is a node whose total degree exceeds the threshold.

        Args:
            threshold: Minimum total degree to be considered a hub.

        Returns:
            List of dicts with node info and degree, sorted by degree descending.
        """
        rows = self.conn.execute(
            """
            SELECT n.id, n.type, n.name, n.file_path,
                   (
                       SELECT COUNT(*) FROM edges e WHERE e.source_id = n.id
                   ) + (
                       SELECT COUNT(*) FROM edges e WHERE e.target_id = n.id
                   ) AS total_degree
            FROM nodes n
            WHERE
                (
                    SELECT COUNT(*) FROM edges e WHERE e.source_id = n.id
                ) + (
                    SELECT COUNT(*) FROM edges e WHERE e.target_id = n.id
                ) > ?
            ORDER BY total_degree DESC
            LIMIT 100
            """,
            (threshold,),
        ).fetchall()

        return [
            {
                "id": r["id"],
                "type": r["type"],
                "name": r["name"],
                "file_path": r["file_path"],
                "total_degree": r["total_degree"],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        """Return summary statistics about the graph store.

        Returns:
            Dict with counts and metadata.
        """
        node_count = self.conn.execute("SELECT COUNT(*) as cnt FROM nodes").fetchone()["cnt"]
        edge_count = self.conn.execute("SELECT COUNT(*) as cnt FROM edges").fetchone()["cnt"]
        file_count = self.conn.execute("SELECT COUNT(*) as cnt FROM file_state").fetchone()["cnt"]

        # Node type distribution.
        type_rows = self.conn.execute(
            "SELECT type, COUNT(*) as cnt FROM nodes GROUP BY type ORDER BY cnt DESC"
        ).fetchall()
        type_dist = {r["type"]: r["cnt"] for r in type_rows}

        # Edge relation distribution.
        relation_rows = self.conn.execute(
            "SELECT relation, COUNT(*) as cnt FROM edges GROUP BY relation ORDER BY cnt DESC"
        ).fetchall()
        relation_dist = {r["relation"]: r["cnt"] for r in relation_rows}

        # Meta entries.
        meta_rows = self.conn.execute(
            "SELECT key, value FROM meta"
        ).fetchall()
        meta = {r["key"]: r["value"] for r in meta_rows}

        return {
            "node_count": node_count,
            "edge_count": edge_count,
            "file_count": file_count,
            "type_distribution": type_dist,
            "relation_distribution": relation_dist,
            "meta": meta,
        }

    # ------------------------------------------------------------------
    # Meta operations
    # ------------------------------------------------------------------

    def set_meta(self, key: str, value: str) -> None:
        """Set a meta key-value pair."""
        self.conn.execute(
            """
            INSERT INTO meta (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        self.conn.commit()

    def get_meta(self, key: str) -> Optional[str]:
        """Get a meta value by key."""
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            logger.info("GraphStore closed: %s", self.db_path)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
