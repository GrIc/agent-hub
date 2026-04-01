"""
Knowledge Graph for GraphRAG — stores entities and relationships extracted from docs.

Uses NetworkX DiGraph for in-memory graph operations, persisted as JSON on disk.
Designed to coexist with the existing ChromaDB vector store: the graph adds
structural context (dependencies, calls, inheritance) while ChromaDB handles
semantic similarity.

Persistence: .graphdb/knowledge_graph.json (JSON node-link format)
             .graphdb/entity_index.json    (label → node ID mapping for fast lookup)
"""

import json
import logging
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

import networkx as nx
from networkx.readwrite import json_graph

logger = logging.getLogger(__name__)

ENTITY_TYPES = {
    "Module", "Class", "Interface", "Function", "File", "Package",
    "Layer", "Service", "API", "Database", "Config", "Library", "Pattern",
}

RELATION_TYPES = {
    "imports", "calls", "depends_on", "contains", "implements", "extends",
    "uses", "exposes", "configures", "reads_from", "writes_to",
    "inherits", "instantiates", "tested_by",
}


class KnowledgeGraph:
    """Thin wrapper over NetworkX DiGraph with persistence and lookup helpers."""

    def __init__(self, persist_dir: str = ".graphdb"):
        self.persist_dir = Path(persist_dir)
        self.graph_path = self.persist_dir / "knowledge_graph.json"
        self.index_path = self.persist_dir / "entity_index.json"

        self.G: nx.DiGraph = nx.DiGraph()
        self._entity_index: dict[str, str] = {}  # normalized_label → node_id

        self.load()

    # -- Mutation ---------------------------------------------------------------

    def add_node(
        self,
        id: str,
        label: str,
        type: str,
        source_doc: str = "",
        doc_level: str = "",
        **attributes,
    ) -> None:
        """Add or update a node. Merges attributes if node already exists."""
        if self.G.has_node(id):
            existing = self.G.nodes[id]
            # Merge source_docs as a set
            sources = set(existing.get("source_docs", []))
            if source_doc:
                sources.add(source_doc)
            self.G.nodes[id].update({
                "label": label,
                "type": type,
                "source_docs": sorted(sources),
                "doc_level": doc_level,
                **attributes,
            })
        else:
            self.G.add_node(id, **{
                "label": label,
                "type": type,
                "source_docs": [source_doc] if source_doc else [],
                "doc_level": doc_level,
                **attributes,
            })

        # Update entity index
        normalized = label.lower().strip()
        self._entity_index[normalized] = id

    def add_edge(
        self,
        source: str,
        target: str,
        relation: str,
        weight: float = 1.0,
        source_doc: str = "",
        doc_level: str = "",
    ) -> None:
        """Add or update a directed edge."""
        key = (source, target, relation)
        if self.G.has_edge(source, target):
            existing = self.G.edges[source, target]
            # Keep highest weight
            if weight > existing.get("weight", 0):
                existing["weight"] = weight
            # Merge source_docs
            sources = set(existing.get("source_docs", []))
            if source_doc:
                sources.add(source_doc)
            existing["source_docs"] = sorted(sources)
        else:
            self.G.add_edge(source, target, **{
                "relation": relation,
                "weight": weight,
                "source_docs": [source_doc] if source_doc else [],
                "doc_level": doc_level,
            })

    def remove_nodes_by_source(self, source_doc: str) -> int:
        """Remove all nodes/edges attributed solely to a given source doc.

        If a node has multiple source_docs, only the reference is removed.
        Returns the number of nodes fully removed.
        """
        to_remove = []
        for node_id, data in list(self.G.nodes(data=True)):
            sources = set(data.get("source_docs", []))
            if source_doc in sources:
                sources.discard(source_doc)
                if not sources:
                    to_remove.append(node_id)
                else:
                    data["source_docs"] = sorted(sources)

        # Also clean edges
        edges_to_remove = []
        for u, v, data in list(self.G.edges(data=True)):
            sources = set(data.get("source_docs", []))
            if source_doc in sources:
                sources.discard(source_doc)
                if not sources:
                    edges_to_remove.append((u, v))
                else:
                    data["source_docs"] = sorted(sources)

        for u, v in edges_to_remove:
            self.G.remove_edge(u, v)

        for node_id in to_remove:
            # Remove from entity index
            label = self.G.nodes[node_id].get("label", "")
            normalized = label.lower().strip()
            self._entity_index.pop(normalized, None)
            self.G.remove_node(node_id)

        return len(to_remove)

    def clear(self) -> None:
        """Remove all nodes and edges."""
        self.G.clear()
        self._entity_index.clear()

    # -- Query -----------------------------------------------------------------

    def get_neighbors(
        self,
        node_id: str,
        max_hops: int = 2,
        relation_filter: Optional[set[str]] = None,
    ) -> dict:
        """BFS traversal from a node. Returns {node_id: hop_distance} for all reachable nodes."""
        if node_id not in self.G:
            return {}

        visited = {node_id: 0}
        frontier = [node_id]

        for hop in range(1, max_hops + 1):
            next_frontier = []
            for current in frontier:
                # Outgoing edges
                for _, neighbor, data in self.G.out_edges(current, data=True):
                    if relation_filter and data.get("relation") not in relation_filter:
                        continue
                    if neighbor not in visited:
                        visited[neighbor] = hop
                        next_frontier.append(neighbor)
                # Incoming edges (reverse traversal for impact analysis)
                for neighbor, _, data in self.G.in_edges(current, data=True):
                    if relation_filter and data.get("relation") not in relation_filter:
                        continue
                    if neighbor not in visited:
                        visited[neighbor] = hop
                        next_frontier.append(neighbor)
            frontier = next_frontier

        return visited

    def find_entities(self, text: str, threshold: float = 0.75) -> list[tuple[str, float]]:
        """Find entity node IDs mentioned in the text.

        Returns list of (node_id, confidence) tuples, sorted by confidence desc.
        Uses exact match first, then fuzzy matching.
        """
        if not self._entity_index:
            return []

        text_lower = text.lower()
        matches = []
        seen = set()

        # Pass 1: exact substring match on labels
        for label_normalized, node_id in self._entity_index.items():
            if len(label_normalized) < 3:
                continue
            if label_normalized in text_lower and node_id not in seen:
                matches.append((node_id, 1.0))
                seen.add(node_id)

        # Pass 2: fuzzy match on remaining tokens (only if few exact matches)
        if len(matches) < 3:
            words = [w for w in text.split() if len(w) >= 3]
            for word in words:
                word_lower = word.lower().strip(".,;:!?()")
                for label_normalized, node_id in self._entity_index.items():
                    if node_id in seen:
                        continue
                    ratio = SequenceMatcher(None, word_lower, label_normalized).ratio()
                    if ratio >= threshold:
                        matches.append((node_id, ratio))
                        seen.add(node_id)

        matches.sort(key=lambda x: -x[1])
        return matches

    def get_subgraph_summary(self, node_ids: dict[str, int]) -> str:
        """Format a human-readable summary of the subgraph for prompt injection.

        Args:
            node_ids: {node_id: hop_distance} from get_neighbors()
        """
        if not node_ids:
            return ""

        lines = []
        # Group by hop distance
        by_hop: dict[int, list[str]] = defaultdict(list)
        for nid, hop in node_ids.items():
            by_hop[hop].append(nid)

        for hop in sorted(by_hop.keys()):
            if hop == 0:
                for nid in by_hop[hop]:
                    data = self.G.nodes.get(nid, {})
                    lines.append(
                        f"[Target] {data.get('label', nid)} ({data.get('type', '?')})"
                    )
            else:
                for nid in by_hop[hop]:
                    data = self.G.nodes.get(nid, {})
                    # Find the relationship edge
                    relations = []
                    for u, v, edata in self.G.edges(data=True):
                        if (u in node_ids and v == nid) or (v in node_ids and u == nid):
                            src_label = self.G.nodes.get(u, {}).get("label", u)
                            tgt_label = self.G.nodes.get(v, {}).get("label", v)
                            relations.append(
                                f"{src_label} --{edata.get('relation', '?')}--> {tgt_label}"
                            )
                    if relations:
                        for rel in relations[:3]:  # Limit per node
                            lines.append(f"  [hop {hop}] {rel}")
                    else:
                        lines.append(
                            f"  [hop {hop}] {data.get('label', nid)} ({data.get('type', '?')})"
                        )

        return "\n".join(lines[:50])  # Cap output length

    def get_source_files_for_nodes(self, node_ids: dict[str, int]) -> set[str]:
        """Get all source doc paths associated with the given nodes."""
        sources = set()
        for nid in node_ids:
            data = self.G.nodes.get(nid, {})
            for src in data.get("source_docs", []):
                sources.add(src)
        return sources

    # -- Persistence -----------------------------------------------------------

    def save(self) -> None:
        """Persist graph and entity index to disk."""
        self.persist_dir.mkdir(parents=True, exist_ok=True)

        data = json_graph.node_link_data(self.G)
        self.graph_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        self.index_path.write_text(
            json.dumps(self._entity_index, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        logger.info(f"[Graph] Saved: {self.node_count} nodes, {self.edge_count} edges")

    def load(self) -> None:
        """Load graph and entity index from disk. No-op if files don't exist."""
        if self.graph_path.exists():
            try:
                data = json.loads(self.graph_path.read_text(encoding="utf-8"))
                self.G = json_graph.node_link_graph(data, directed=True)
                logger.info(f"[Graph] Loaded: {self.node_count} nodes, {self.edge_count} edges")
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"[Graph] Cannot load graph: {e}")
                self.G = nx.DiGraph()

        if self.index_path.exists():
            try:
                self._entity_index = json.loads(
                    self.index_path.read_text(encoding="utf-8")
                )
            except (json.JSONDecodeError, Exception):
                self._rebuild_index()
        else:
            self._rebuild_index()

    def _rebuild_index(self) -> None:
        """Rebuild entity index from graph nodes."""
        self._entity_index = {}
        for node_id, data in self.G.nodes(data=True):
            label = data.get("label", "")
            if label:
                self._entity_index[label.lower().strip()] = node_id

    # -- Stats -----------------------------------------------------------------

    @property
    def node_count(self) -> int:
        return self.G.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self.G.number_of_edges()

    def stats(self) -> dict:
        """Return statistics about the graph."""
        node_types = defaultdict(int)
        for _, data in self.G.nodes(data=True):
            node_types[data.get("type", "unknown")] += 1

        relation_types = defaultdict(int)
        for _, _, data in self.G.edges(data=True):
            relation_types[data.get("relation", "unknown")] += 1

        return {
            "nodes": self.node_count,
            "edges": self.edge_count,
            "node_types": dict(node_types),
            "relation_types": dict(relation_types),
            "connected_components": nx.number_weakly_connected_components(self.G),
        }
