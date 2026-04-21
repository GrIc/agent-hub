# ADR 0001: Extract Project Pipeline to Sister Repository

## Status

Accepted

## Context

The greenfield project pipeline (`portfolio → specifier → planner → storyteller → presenter → code`) was initially developed as part of Agent Hub. This pipeline targets a different user persona (PM/architect doing greenfield design) and dilutes Agent Hub's core positioning as "MCP server for code intelligence on large codebases."


The pipeline competes with dedicated greenfield design tools and doesn't align with our existential constraint: **zero hallucination in MCP tool responses**. The pipeline's complexity increases maintenance burden and confuses users about Agent Hub's core value proposition.


## Decision

Extract the greenfield project pipeline to a sister repository `agent-hub-projects` while preserving git history. Agent Hub will focus exclusively on MCP server functionality for large, under-documented codebases.

## Consequences

### Positive
- Agent Hub has a clear, singular purpose: MCP server for code intelligence
- Reduced maintenance burden (no project pipeline code in main repo)
- Better user experience (no confusion between greenfield design and codebase understanding)
- Clear separation of concerns between the two products


### Negative
- Users wanting greenfield design capabilities must install both repos
- Migration effort for existing users of the pipeline
- Need to maintain documentation and examples for the sister repo

### Neutral
- Git history preserved in sister repo
- Project pipeline can evolve independently
- Agent Hub remains focused on its core competency

## Implementation Plan

1. Create `agent-hub-projects` repository
2. Use `git filter-repo` to extract pipeline files while preserving history
3. Update Agent Hub documentation to reference sister repo
4. Remove pipeline code and configuration from Agent Hub
5. Update CI/CD to build both repos

## Related Decisions

- DECIDE-1: Extract project pipeline to sister repo
- T-001: Execute extraction

---

**See Also:**
- [T-001 — Extract project pipeline to `agent-hub-projects`](T-001-extract-projects.md)
- [Phase 0 — Cleanup](../roadmap/00_MASTER_ROADMAP.md#phase-0--cleanup-1-week)
