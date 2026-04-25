# ADR 0006: Multi-Repository Support in Phase 5

## Status

Accepted

## Context

Agent Hub currently assumes a single codebase in `workspace/`. This limits its usefulness for:
- Multi-repository projects (monorepos, polyrepos)
- Cross-repository dependency analysis
- Large organizations with many repositories
- Projects spanning multiple languages/repos




To provide senior-engineer-level knowledge across large codebases, Agent Hub needs to support multiple repositories simultaneously.




## Decision

Add multi-repository support in Phase 5. This includes:
- Configuration for multiple repositories
- Indexing multiple repositories into the same ChromaDB
- Cross-repository search and analysis
- Repository-aware tooling




## Consequences

### Positive
- Agent Hub can handle large, multi-repository codebases
- Better alignment with enterprise use cases
- Enables cross-repository analysis and insights
- Future-proof for large-scale development




### Negative
- Increased complexity in configuration and indexing
- Higher resource requirements (multiple repositories to index)
- Longer implementation timeline (Phase 5: 4 weeks)
- Need to maintain backward compatibility with single-repo setups



### Neutral
- Existing single-repo setups continue to work unchanged
- Multi-repo is opt-in via configuration
- No impact on current MCP tool contracts



## Implementation Plan

1. **Configuration**: Update `config.yaml` to support multiple repositories
2. **Indexing**: Modify ingestion pipeline to handle multiple repositories
3. **Search**: Update search logic to handle cross-repository queries
4. **Tools**: Add repository-aware parameters to MCP tools
5. **Documentation**: Update client guides for multi-repo setups


## Related Decisions

- DECIDE-6: Multi-repo support in Phase 5
- T-503: Execute multi-repo support
- Phase 5: Advanced features


---

**See Also:**
- [Phase 5 — Advanced features](../roadmap/05_PHASE_ADVANCED.md)
- [Configuration Guide](../operations/deploy.md)
