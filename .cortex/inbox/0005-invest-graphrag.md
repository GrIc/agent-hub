# ADR 0005: Invest in GraphRAG

## Status

Accepted

## Context

Large codebases have knowledge distributed across multiple dimensions:
- **Text layer**: Raw source code
- **Structure layer**: Module hierarchy, imports, inheritance
- **Semantics layer**: Meaning and relationships between components
- **Conventions layer**: Team-specific patterns and idioms
- **History layer**: Evolution, rationale, and architectural decisions




Current RAG (Retrieval-Augmented Generation) only captures the text layer effectively. To provide senior-engineer-level knowledge, we need to capture relationships and semantics through:
- Call graphs and dependency analysis
- Entity relationships (classes, functions, modules)
- Architectural patterns and conventions
- Historical context and evolution




## Decision

Invest in GraphRAG (Graph Retrieval-Augmented Generation) for Phase 2. GraphRAG combines:
- **Vector search** (existing RAG) for text similarity
- **AST analysis** for structural understanding
- **Knowledge graph** for entity relationships and semantic connections
- **LLM hybrid** for combining results and generating insights




GraphRAG will enable queries like:
- "Show me all components that depend on the UserService"
- "Find all classes that implement the Repository pattern"
- "What are the main entry points of the backend API?"
- "Show me the call graph for the checkout flow"




## Consequences

### Positive
- Significantly improved codebase understanding capabilities
- Better answers to architectural and dependency questions
- Enables "senior engineer" level insights
- Future-proof foundation for advanced analysis tools




### Negative
- Increased complexity (three search modalities instead of one)
- Higher resource requirements (knowledge graph storage and traversal)
- Longer implementation timeline (Phase 2: 3 weeks)
- Need to maintain three search backends



### Neutral
- Existing RAG pipeline remains the primary search method
- GraphRAG augments, not replaces, existing search
- Phase 2 investment (3 weeks) with parallelizable work



## Implementation Plan

1. **Phase 2a: Knowledge Graph Infrastructure**
   - Implement AST parser for Python/TypeScript/JavaScript
   - Build entity extraction pipeline
   - Create knowledge graph storage layer
   - Implement basic graph traversal queries

2. **Phase 2b: Hybrid Search Engine**
   - Integrate vector search with graph traversal
   - Implement result merging and ranking
   - Add LLM-based query rewriting and result synthesis

3. **Phase 2c: Tool Integration**
   - Expose graph-based tools via MCP
   - Update existing tools to use hybrid search
   - Add new tools for graph analysis

## Related Decisions

- DECIDE-5: Invest in GraphRAG
- Phase 2: GraphRAG Investment


---

**See Also:**
- [Phase 2 — GraphRAG Investment](../roadmap/02_PHASE_GRAPHRAG.md)
- [Architecture Overview](../architecture.md)
