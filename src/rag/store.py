"""
ChromaDB-backed vector store for RAG.
Handles embedding, storage, and retrieval.

Supports hierarchical search via doc_level metadata:
  - L0/L1/L2: Synthesis docs (high-level)
  - L3: Codex scan docs (per-file)
  - code: Raw source code
  - context: Manual docs
  - report: Agent reports

Supports cross-encoder reranking when a rerank model is configured.
Supports metadata filtering on doc_level, module, and content_type.
"""

import hashlib
import logging
import sys
from typing import Optional

try:
    import pysqlite3
    sys.modules["sqlite3"] = pysqlite3
except ImportError:
    pass

import chromadb

logger = logging.getLogger(__name__)

# Level groups for hierarchical search
import re as _re

LEVELS_DETAIL    = ["L3", "code", "context"]
LEVELS_DETAIL_RE = set(LEVELS_DETAIL + ["report"])

def _is_synthesis_level(level: str) -> bool:
    """True for any LN level from synthesize.py (L0, L1, L2, L4, L7...) except L3."""
    return bool(_re.match(r"^L\d+$", level)) and level != "L3"


class VectorStore:
    """Thin wrapper around ChromaDB + remote embeddings + optional reranking."""

    def __init__(
        self,
        client: "src.client.ResilientClient",
        persist_dir: str = ".vectordb",
        collection_name: str = "context",
        embed_model: Optional[str] = None,
        rerank_model: Optional[str] = None,
    ):
        self.llm_client = client
        self.embed_model = embed_model or ""
        self.rerank_model = rerank_model or ""
        self.graph = None  # Optional KnowledgeGraph, set externally

        self.db = chromadb.PersistentClient(path=persist_dir)
        self.collection = self.db.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            f"VectorStore ready: {self.collection.count()} docs in '{collection_name}'"
            + (f", rerank={self.rerank_model}" if self.rerank_model else "")
        )

    def add_chunks(self, chunks: list[dict], batch_size: int = 8) -> int:
        """
        Embed and store chunks. Deduplicates by content hash.
        Each chunk dict should have: text, source, chunk_index, doc_level,
        block, module, content_type.
        """
        if not chunks:
            return 0

        new_chunks = []
        for chunk in chunks:
            doc_id = hashlib.md5(chunk["text"].encode()).hexdigest()
            new_chunks.append((doc_id, chunk))

        existing_ids = set()
        check_batch = 100
        for i in range(0, len(new_chunks), check_batch):
            batch_ids = [c[0] for c in new_chunks[i:i + check_batch]]
            try:
                result = self.collection.get(ids=batch_ids)
                existing_ids.update(result["ids"])
            except Exception:
                pass

        filtered = [(did, chunk) for did, chunk in new_chunks if did not in existing_ids]

        if not filtered:
            logger.info("No new chunks to add (all already indexed)")
            return 0

        logger.info(f"{len(filtered)} new chunks to embed (skipped {len(new_chunks) - len(filtered)} existing)")

        added = 0
        total_batches = (len(filtered) + batch_size - 1) // batch_size
        for i in range(0, len(filtered), batch_size):
            batch = filtered[i : i + batch_size]
            batch_num = i // batch_size + 1
            ids = [c[0] for c in batch]
            texts = [c[1]["text"] for c in batch]
            metadatas = [
                {
                    "source": c[1].get("source", ""),
                    "doc_level": c[1].get("doc_level", "context"),
                    "block": c[1].get("block", ""),
                    "module": c[1].get("module", ""),
                    "content_type": c[1].get("content_type", ""),
                    "chunk_index": c[1].get("chunk_index", 0),
                }
                for c in batch
            ]

            try:
                embeddings = self.llm_client.embed(texts, model=self.embed_model)
                seen_ids = set()
                unique_ids = []
                unique_docs = []
                unique_metas = []
                unique_embeds = []
                for idx, doc_id in enumerate(ids):
                    if doc_id not in seen_ids:
                        seen_ids.add(doc_id)
                        unique_ids.append(doc_id)
                        unique_docs.append(texts[idx])
                        unique_metas.append(metadatas[idx])
                        unique_embeds.append(embeddings[idx])
                    else:
                        print(f"Ignored duplicate ID in batch: {doc_id}")
                self.collection.add(
                    ids=unique_ids,
                    embeddings=unique_embeds,
                    documents=unique_docs,
                    metadatas=unique_metas,
                )
                added += len(batch)
                if batch_num % 10 == 0 or batch_num == total_batches:
                    logger.info(f"Progress: {batch_num}/{total_batches} batches ({added} chunks added)")
            except Exception as e:
                logger.error(f"Batch {batch_num}/{total_batches} failed: {e} -- skipping")

        logger.info(f"Total added: {added} new chunks (store total: {self.collection.count()})")
        return added

    def _get_synthesis_levels(self) -> list[str]:
        """
        Discover which synthesis levels (L0, L1, L2, L4...) are present in the
        current index by sampling metadata. Falls back to ["L0", "L1", "L2"] if
        the index is empty or has no doc_level metadata.
        """
        try:
            # Sample up to 1000 chunks to find all distinct doc_level values
            result = self.collection.get(
                limit=1000,
                include=["metadatas"],
            )
            levels = set()
            for meta in result.get("metadatas") or []:
                lvl = meta.get("doc_level", "")
                if _is_synthesis_level(lvl):
                    levels.add(lvl)
            if levels:
                return sorted(levels)
        except Exception as e:
            logger.debug(f"Could not discover synthesis levels: {e}")

        # Fallback for empty or legacy indexes
        return ["L0", "L1", "L2"]

    def search(
        self,
        query: str,
        top_k: int = 8,
        doc_levels: Optional[list[str]] = None,
        module: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> list[dict]:
        """
        Search for relevant chunks with optional metadata filtering.

        Args:
            query: Search query
            top_k: Number of results
            doc_levels: Optional filter on doc_level metadata (e.g., ["L0", "L1", "L2"])
            module: Optional filter on module metadata
            content_type: Optional filter on content_type metadata

        Returns:
            List of {text, source, score, doc_level}.
        """
        if self.collection.count() == 0:
            return []

        try:
            query_embedding = self.llm_client.embed([query], model=self.embed_model)[0]
        except Exception as e:
            logger.error(f"Failed to embed query: {e}")
            return []

        where_filter = {}
        if doc_levels:
            where_filter["doc_level"] = {"$in": doc_levels}
        if module:
            where_filter["module"] = module
        if content_type:
            where_filter["content_type"] = content_type
        
        # Only pass where_filter if it has conditions
        where_clause = where_filter if where_filter else None

        try:
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=min(top_k, self.collection.count()),
                include=["documents", "metadatas", "distances"],
                where=where_clause,
            )
        except Exception as e:
            # Fallback: if filter fails (e.g., old index without metadata), search without filter
            logger.warning(f"Filtered search failed ({e}), falling back to unfiltered search")
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=min(top_k, self.collection.count()),
                include=["documents", "metadatas", "distances"],
            )

        output = []
        if results["documents"]:
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                output.append({
                    "text": doc,
                    "source": meta.get("source", ""),
                    "score": 1 - dist,
                    "doc_level": meta.get("doc_level", ""),
                })

        return output

    def search_with_rerank(
        self,
        query: str,
        retrieve_k: int = 15,
        final_k: int = 8,
        doc_levels: Optional[list[str]] = None,
        module: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> list[dict]:
        """
        Retrieve candidates via embedding, then rerank with cross-encoder.

        If no rerank model is configured, falls back to embedding-only results.
        
        Args:
            query: Search query
            retrieve_k: Number of candidates to retrieve for reranking (capped at 10)
            final_k: Number of final results to return
            doc_levels: Optional filter on doc_level metadata
            module: Optional filter on module metadata
            content_type: Optional filter on content_type metadata

        Returns:
            List of reranked results with scores.
        """
        # Cap retrieve_k at 10 documents for reranker
        retrieve_k = min(retrieve_k, 10)
        
        # Over-retrieve candidates for reranking
        candidates = self.search(
            query,
            top_k=retrieve_k,
            doc_levels=doc_levels,
            module=module,
            content_type=content_type,
        )

        if not candidates or not self.rerank_model:
            return candidates[:final_k]

        # Rerank via cross-encoder API
        documents = [c["text"] for c in candidates]
        try:
            rankings = self.llm_client.rerank(
                query=query,
                documents=documents,
                model=self.rerank_model,
                top_k=final_k,
            )

            reranked = []
            for r in rankings:
                idx = r["index"]
                if 0 <= idx < len(candidates):
                    result = dict(candidates[idx])
                    result["rerank_score"] = r["score"]
                    reranked.append(result)

            return reranked[:final_k]

        except Exception as e:
            logger.warning(f"Reranking failed ({e}), using embedding scores")
            return candidates[:final_k]

    def search_hierarchical(
        self,
        query: str,
        top_k: int = 8,
        doc_levels: Optional[list[str]] = None,
        module: Optional[str] = None,
        content_type: Optional[str] = None,
    ) -> list[dict]:
        """
        Two-pass hierarchical search with optional cross-encoder reranking and metadata filtering.

        1. First pass: synthesis docs (all LN levels except L3) for architectural context
        2. Second pass: detailed docs (L3, code, context) for implementation details
        3. Merge and deduplicate by source, sorted by (rerank) score

        Falls back to flat search if the index has no doc_level metadata.
        
        Args:
            query: Search query
            top_k: Number of results to return
            doc_levels: Optional filter on doc_level metadata
            module: Optional filter on module metadata
            content_type: Optional filter on content_type metadata

        Returns:
            List of merged and deduplicated results.
        """
        half_k = max(top_k // 2, 2)
        retrieve_k = max(top_k * 2, 15)  # Over-retrieve for reranking

        # Discover synthesis levels dynamically (handles L4, L5... from synthesize.py)
        synthesis_levels = self._get_synthesis_levels()

        # Pass 1: high-level synthesis (with reranking)
        synthesis_results = self.search_with_rerank(
            query,
            retrieve_k=retrieve_k,
            final_k=half_k,
            doc_levels=synthesis_levels if doc_levels is None else doc_levels,
            module=module,
            content_type=content_type,
        )

        # Pass 2: detailed docs (with reranking)
        detail_results = self.search_with_rerank(
            query,
            retrieve_k=retrieve_k,
            final_k=half_k,
            doc_levels=LEVELS_DETAIL if doc_levels is None else doc_levels,
            module=module,
            content_type=content_type,
        )

        # If both empty, fall back to flat search (legacy index without doc_level)
        if not synthesis_results and not detail_results:
            logger.debug("Hierarchical search returned nothing, falling back to flat search")
            return self.search_with_rerank(
                query, retrieve_k=retrieve_k, final_k=top_k,
            )

        # Merge and deduplicate (prefer higher score when same source)
        seen = {}
        for result in synthesis_results + detail_results:
            key = result["source"] + "|" + result["text"][:100]
            score = result.get("rerank_score", result["score"])
            existing_score = seen[key].get("rerank_score", seen[key]["score"]) if key in seen else -1
            if score > existing_score:
                seen[key] = result

        merged = sorted(
            seen.values(),
            key=lambda r: r.get("rerank_score", r["score"]),
            reverse=True,
        )
        return merged[:top_k]

    def search_hybrid(
        self,
        query: str,
        top_k: int = 8,
        doc_levels: Optional[list[str]] = None,
        module: Optional[str] = None,
        content_type: Optional[str] = None,
        **kwargs,
    ) -> list[dict]:
        """Hybrid search: vector + knowledge graph.

        If a KnowledgeGraph is attached (self.graph), combines vector results
        with graph traversal for structural context. Otherwise falls back to
        search_hierarchical().
        
        Args:
            query: Search query
            top_k: Number of results to return
            doc_levels: Optional filter on doc_level metadata
            module: Optional filter on module metadata
            content_type: Optional filter on content_type metadata
            **kwargs: Additional arguments for HybridSearcher

        Returns:
            List of search results.
        """
        if self.graph is None or self.graph.node_count == 0:
            return self.search_hierarchical(
                query,
                top_k=top_k,
                doc_levels=doc_levels,
                module=module,
                content_type=content_type,
            )

        from src.rag.graph_search import HybridSearcher

        searcher = HybridSearcher(
            store=self,
            graph=self.graph,
            max_hops=kwargs.get("max_hops", 2),
            graph_boost=kwargs.get("graph_boost", 0.3),
        )
        return searcher.search(query, top_k=top_k)

    def clear(self):
        name = self.collection.name
        self.db.delete_collection(name)
        self.collection = self.db.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("Vector store cleared")

    def purge_chunks_by_source(self, source: str) -> int:
        """Remove all chunks from ChromaDB attributed to a given source file.

        Args:
            source: The source file path (relative to workspace) to purge.

        Returns:
            Number of chunks removed.
        """
        try:
            # Retrieve all chunk IDs with this source
            result = self.collection.get(
                where={"source": source},
                include=["metadatas", "ids"],
            )
            if not result["ids"]:
                return 0

            # Delete the chunks
            self.collection.delete(ids=result["ids"])
            logger.info(f"Purged {len(result['ids'])} chunks for source: {source}")
            return len(result["ids"])
        except Exception as e:
            logger.error(f"Failed to purge chunks for source {source}: {e}")
            return 0

    @property
    def count(self) -> int:
        return self.collection.count()