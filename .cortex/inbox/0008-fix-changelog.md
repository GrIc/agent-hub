# ADR 0008: Fix & Enrich Changelog

## Status

Accepted

## Context

The current changelog system (time-travel documentation via `watch.py`) generates simple narrative entries but lacks:
- **Semantic structure**: Machine-readable format for querying and analysis
- **Entity extraction**: Automatic identification of changed components (classes, functions, modules)
- **Impact analysis**: Understanding what else might be affected by changes
- **Cross-referencing**: Linking to related changes, PRs, issues
- **Searchability**: Easy to find changes by component, date, or type






Without a proper changelog system, teams lose historical context and struggle to understand codebase evolution.





## Decision

Rebuild the changelog system in Phase 3 with:
- **Semantic changelog format**: Structured, machine-readable entries
- **Entity extraction**: Automatic identification of changed components using AST analysis
- **Impact analysis**: Cross-referencing with call graphs and dependencies
- **Search and query**: Easy to find and analyze changes
- **Integration**: Automatic updates to wiki and documentation






The new changelog will be generated daily and stored in a structured format (JSON/YAML) with links to source code and related artifacts.






## Consequences

### Positive
- Machine-readable changelog enables advanced analysis and querying
- Automatic entity extraction provides better historical context
- Impact analysis helps understand change ripple effects
- Integration with documentation keeps artifacts up-to-date
- Better alignment with "senior engineer" knowledge requirements





### Negative
- Breaking change: Old changelog format no longer supported
- Need to migrate existing changelog entries
- Increased complexity in changelog generation
- Longer implementation timeline (Phase 3: 2 weeks)





### Neutral
- Existing time-travel functionality preserved (human-readable view)
- New changelog augments, not replaces, existing system
- Phase 3 investment (2 weeks) with parallelizable work





## Implementation Plan

1. **Phase 3a: Changelog Infrastructure**
   - Design semantic changelog format
   - Implement AST-based entity extraction
   - Build changelog storage and indexing
   - Create search and query API

2. **Phase 3b: Integration**
   - Integrate with documentation generation
   - Update wiki generation to include changelog entries
   - Add changelog browser to web UI
3. **Phase 3c: Migration**
   - Migrate existing changelog entries to new format
   - Update documentation and guides



## Related Decisions

- DECIDE-8: Fix & enrich changelog
- T-301: Execute changelog rebuild
- Phase 3: Changelog Fix



---


**See Also:**
- [Phase 3 — Changelog Fix](../roadmap/03_PHASE_CHANGELOG.md)
- [Architecture Overview](../architecture.md)
