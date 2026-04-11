# Project Context for Coding Agents

## What is this project?

Agent Hub (athanor-ai) is a self-hosted multi-agent AI platform for codebase documentation and RAG-powered code Q&A.

## Key pipeline

1. `codex.py` scans source files → generates per-file markdown docs in `context/docs/`
2. `synthesize.py` builds a hierarchical pyramid (L3→L2→L1→L0) from codex docs
3. `ingest.py` chunks all docs + source code → embeds into ChromaDB
4. `build_graph.py` extracts entity-relation triplets → builds a knowledge graph
5. `store.py` serves RAG queries with hierarchical search + reranking

## Critical files

- `src/agents/codex.py` — CodexAgent class, `/scan` command
- `synthesize.py` — Synthesizer class, `build_all()` method
- `src/rag/ingest.py` — chunking and embedding
- `src/rag/store.py` — VectorStore, `search_hierarchical()`
- `build_graph.py` — GraphRAG triplet extraction
- `agents/defs/codex.md` — system prompt for codex agent
- `config.yaml` — all configuration

## Known issues being fixed

- Hallucinated class/method names in codex docs
- Hallucination propagation through synthesis levels
- Flat metadata in chunks (missing module, block, content_type)
- Unconstrained graph triplet extraction
