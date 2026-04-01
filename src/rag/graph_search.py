"""
Hybrid search combining vector store (ChromaDB) with graph traversal (NetworkX).

Algorithm:
  1. Entity extraction from query — match against known graph entities
  2. Graph traversal — BFS from matched entities, collect subgraph
  3. Merge with vector results — boost scores for results whose source
     appears in the graph neighborhood
  4. Inject structural context — add a "Graph context" summary to results

Falls back to plain search_hierarchical() if the graph is empty or
no entities are matched.
"""

import logging
from typing import Optional

from src.rag.graph import KnowledgeGraph

logger = logging.getLogger(__name__)


class HybridSearcher:
    """Combines vector search with knowledge graph traversal."""

    def __init__(
        self,
        store,
        graph: KnowledgeGraph,
        max_hops: int = 2,
        graph_boost: float = 0.3,
    ):
        self.store = store
        self.graph = graph
        self.max_hops = max_hops
        self.graph_boost = graph_boost

    def search(
        self,
        query: str,
        top_k: int = 8,
        relation_filter: Optional[set[str]] = None,
    ) -> list[dict]:
        """Hybrid search: vector + graph.

        Returns list of {text, source, score, doc_level, graph_context?}
        in the same format as search_hierarchical().
        """
        # Phase 1: vector search (always run)
        vector_results = self.store.search_hierarchical(query, top_k=top_k)

        # If graph is empty, return vector results as-is
        if self.graph.node_count == 0:
            return vector_results

        # Phase 2: entity matching from query
        entity_matches = self.graph.find_entities(query, threshold=0.75)

        if not entity_matches:
            # No graph entities found — return vector results unchanged
            return vector_results

        # Phase 3: graph traversal from matched entities
        all_neighbors: dict[str, int] = {}
        for node_id, _confidence in entity_matches[:5]:  # Limit seed entities
            neighbors = self.graph.get_neighbors(
                node_id,
                max_hops=self.max_hops,
                relation_filter=relation_filter,
            )
            for nid, hop in neighbors.items():
                if nid not in all_neighbors or hop < all_neighbors[nid]:
                    all_neighbors[nid] = hop

        # Collect source files from graph neighborhood
        graph_sources = self.graph.get_source_files_for_nodes(all_neighbors)

        # Phase 4: boost vector results whose source appears in graph neighborhood
        boosted_results = []
        for result in vector_results:
            result = dict(result)  # Don't mutate original
            source = result.get("source", "")
            base_score = result.get("rerank_score", result.get("score", 0))

            if source in graph_sources:
                # Find the minimum hop distance for this source
                min_hop = float("inf")
                for nid, hop in all_neighbors.items():
                    node_data = self.graph.G.nodes.get(nid, {})
                    if source in node_data.get("source_docs", []):
                        min_hop = min(min_hop, max(hop, 1))

                if min_hop < float("inf"):
                    boost = self.graph_boost / min_hop
                    result["score"] = base_score * (1 + boost)
                    result["graph_boosted"] = True

            boosted_results.append(result)

        # Re-sort by boosted score
        boosted_results.sort(
            key=lambda r: r.get("score", 0),
            reverse=True,
        )

        # Phase 5: generate structural context summary
        graph_context = self.graph.get_subgraph_summary(all_neighbors)
        if graph_context:
            # Attach to the first result (will be extracted by base.py)
            if boosted_results:
                boosted_results[0]["graph_context"] = graph_context
            else:
                # No vector results but we have graph context
                boosted_results.append({
                    "text": "",
                    "source": "knowledge_graph",
                    "score": 0.5,
                    "doc_level": "graph",
                    "graph_context": graph_context,
                })

        return boosted_results[:top_k]
