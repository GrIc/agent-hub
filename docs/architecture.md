# Agent Hub — Architecture Overview

Agent Hub is an MCP server designed to provide AI coding agents with senior-engineer-level knowledge of large codebases (100k–10M LOC). It exposes codebase knowledge through structured MCP tools and a hybrid search pipeline combining vector search, AST analysis, and GraphRAG.

## Core Components

### 1. MCP Server Layer (`src/mcp_server.py`)

- Exposes 29+ MCP tools across 8 categories
- Tools are grouped by functional domain for discoverability
- All tool outputs include `sources` field for grounding verification

**Tool Categories:**
- Code Intelligence: `expert_ask`, `search_rag`, `search_graph`
- File Operations: `read_file`, `edit_file`
- Project Management: `list_deliverables`, `read_deliverable`, `apply_deliverable`
- Documentation: `list_wiki_pages`, `read_wiki_page`
- Analysis: `call_graph`, `impact_preview`
- Discovery: `discover_patterns`, `discover_conventions`
- Utilities: `list_tools`, `ping`

### 2. Hybrid Search Pipeline (`src/rag/`)

The search pipeline operates in two passes with cross-encoder reranking:

```
Pass 1: Architecture-level search (L0, L1, L2 synthesis docs)
       ↓
eranked results
       ↓
Pass 2: Implementation-level search (L3 docs + raw code chunks)
       ↓
Merge & deduplicate → Final context
```

**Components:**
- [`src/rag/grounding.py`](src/rag/grounding.py): Source verification and citation contract enforcement
- [`src/rag/store.py`](src/rag/store.py): ChromaDB vector store with hierarchical search
- [`src/rag/graph.py`](src/rag/graph.py): Knowledge graph for entity relationships (Phase 2)
- [`src/rag/ingest.py`](src/rag/ingest.py): Document parsing and chunking pipeline

### 3. Agent Framework (`src/agents/`)

Agents are defined in Markdown files (`agents/defs/*.md`) and loaded dynamically:

**Core Agents:**
- `expert`: Primary code Q&A, review, and debugging assistant
- `documenter`: Architecture documentation and Mermaid diagram generation
- `codex`: Codebase scanning and L3 documentation generation

**Custom Agents:**
- Any `.md` file in `agents/defs/` with `web: yes` appears in the web UI
- Agents can declare peers for cross-agent collaboration
- System prompts are constructed from definition files

### 4. Documentation Pyramid

Agent Hub builds a dynamic documentation hierarchy from your codebase:

```
L0  ARCHITECTURE_OVERVIEW.md          (1 file — the big picture)
L1+ L1_backend.md, L2_backend_api.md  (intermediate layers, depth varies by codebase)
L3  codex_*.md                         (1 per source file, raw code + generated docs)
```

**Generation Flow:**
```
workspace/ → codex scan → L3 docs → synthesize → L2/L1 → L0
                                      ↓
                                 ChromaDB index
```

### 5. Web Interface (`web/server.py`)

- FastAPI server serving `/debug/chat`, `/v1/*`, `/mcp/sse`, and documentation routes
- Session management for conversation history
- Statistics and logging endpoints
- Admin landing page at `/admin` (T-005 placeholder)

### 6. Indexer Pipeline (`watch.py`, `synthesize.py`)

**watch.py:**
- Incremental change detection
- Triggers re-scan and re-synthesis for modified files
- Generates time-travel changelog entries

**synthesize.py:**
- Bottom-up aggregation of documentation pyramid
- Dynamic level numbering based on code hierarchy depth
- Preserves architectural context across layers

## Data Flow

```
Codebase (workspace/)
    ↓
Codex Agent (/scan)
    ↓
L3 Documentation (codex_*.md)
    ↓
Synthesize (L3→L2→L1→L0)
    ↓
ChromaDB Index (.vectordb/)
    ↓
MCP Tools (expert_ask, search_rag, etc.)
    ↓
AI Coding Agents (Roo Code, Continue.dev, etc.)
```

## Deployment Architecture

### Single-Container Mode (docker-compose.yml)

```
┌───────────────────────────────────────────────────────────────┐
│                   Agent Hub Container (:8080)              │
│                                                           │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────┐  │
│  │   Web UI   │    │   MCP SSE   │    │  FastAPI API   │  │
│  │  /debug/*  │    │  /mcp/sse   │    │  /v1/*         │  │
│  └─────────────┘    └─────────────┘    └─────────────────┘  │
│        ↓                   ↓                   ↓            │
│  Chat Interface      Tool Calls      Chat Completions    │
│                                                           │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │                 ChromaDB (.vectordb)              │  │
│  └─────────────────────────────────────────────────────────┘  │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │               Knowledge Graph (.graphdb)             │  │
│  └─────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────┘
```

### IDE Integration Mode

```
VS Code / IntelliJ / Cursor  ←mcp→  Agent Hub (:8080/mcp/sse)
                                ↓
                    Open WebUI (:3000)
                         (optional chat UI)
```

## Configuration

Agent Hub uses two configuration files with clear separation:

| File | Purpose | Versioned |
|------|---------|-----------|
| `.env` | Secrets and environment (API keys, Docker paths) | No (`.gitignore`) |
| `config.yaml` | Application configuration (models, agents, RAG settings) | Yes |

**Example config.yaml:**
```yaml
models:
  heavy: gpt-4o                    # Best reasoning model
  code: gpt-4o                     # Code-specialized
  light: gpt-4o-mini               # Fast/cheap
  embed: text-embedding-3-small    # Embeddings
  rerank: ""                       # Cross-encoder (optional)

rag:
  rerank_top_k: 8                 # Top K chunks to rerank
  hierarchical_search: true        # Enable L0→L3 search

# Domain-specific customization
custom_dsl:
  name: "HQL"
  description: "Hibernate Query Language for database queries."

domain:
  sector: "fintech"
  product_type: "lending platform"
  glossary:
    - term: "RiskScore"
      definition: "Credit score 0-1000"
```

## Quality Gates

All outputs are validated against these constraints:

1. **Source Grounding**: Every name referenced must exist in the source
2. **Citation Contract**: Tools return `sources: [{path, line_start, line_end}]`
3. **Abstain Over Guess**: Return `INSUFFICIENT_EVIDENCE` instead of fabrication
4. **Schema Validation**: Input/output validation for all MCP tools
5. **English Only**: All generated text is in English
6. **Config Over Code**: Behaviors exposed via `config.yaml` keys
7. **Complete Files**: Deliverables are full files, not patches
8. **Test-First**: New tools include golden tests
9. **Changelog Discipline**: Every PR adds to `CHANGELOG.md`
10. **No New Dependencies**: Requires approval for new pip packages

## Performance Characteristics

- **Index Size**: Scales with codebase size (100k–10M LOC)
- **Search Latency**: <2s for typical queries (with reranking)
- **Memory**: ~512MB per 1M chunks in ChromaDB
- **Throughput**: 50–100 queries/minute per container (depends on LLM)

## Scaling Considerations

- **Horizontal Scaling**: Multiple containers can share the same `.vectordb/` and `.graphdb/` volumes
- **Read Replicas**: ChromaDB supports read replicas for search-heavy workloads
- **Index Updates**: Incremental updates via `watch.py` minimize re-indexing overhead
- **Cold Start**: First query after restart triggers on-demand re-index if needed

## Security Model

- **MCP Tools**: All tool invocations require explicit client authorization
- **API Endpoints**: `/v1/*` endpoints validate model names strictly (`expert-rag` only)
- **File Access**: `read_file`/`edit_file` respect workspace boundaries
- **Telemetry**: Opt-in only (Phase 5, T-504)

## Failure Modes & Mitigations

| Failure Mode | Detection | Mitigation |
|--------------|-----------|------------|
| Missing source in citation | Grounding validation | Return `INSUFFICIENT_EVIDENCE` |
| ChromaDB corruption | Health check `/healthz` | Auto-rebuild on startup |
| LLM API timeout | Client retry logic | Exponential backoff, circuit breaker |
| Disk space exhaustion | Volume monitoring | Alert + graceful degradation |
| Concurrent index updates | File locking | Queue-based serialization |

## Monitoring & Observables

- **Health Endpoint**: `/healthz` returns 200 when ready
- **Stats Endpoint**: `/api/stats` provides query counts, index size, errors
- **Logs**: Structured JSONL logs per day in `web/logs/`
- **Metrics**: Prometheus-style counters for tool invocations and errors

## Future Evolution

- **Phase 2**: GraphRAG integration for entity relationship queries
- **Phase 3**: Changelog enrichment and semantic versioning
- **Phase 4**: MCP tool standardization and golden tests
- **Phase 5**: Multi-repo support and telemetry

---

**See Also:**
- [MCP Tools Reference](docs/mcp/tools.md)
- [Operations Guide](docs/operations/deploy.md)
- [Client Setup Instructions](docs/clients/)
