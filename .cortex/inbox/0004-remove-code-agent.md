# ADR 0004: Remove `code` Agent and `file_edit` MCP Tool

## Status

Accepted

## Context

Cline, Roo Code, Claude Code, and Cursor all provide native file editing capabilities that are superior to Agent Hub's `code` agent + `file_edit` MCP tool. Attempting to compete on edit semantics distracts from Agent Hub's core value: providing senior-engineer-level knowledge of large codebases.



The `file_edit` tool was an attempt to standardize edit semantics across MCP clients, but it's redundant with native IDE editing and creates maintenance burden. We cede the file editing ground to IDEs and focus on knowledge extraction and analysis.



## Decision

Remove the `code` agent and `file_edit` MCP tool entirely. This includes:
- Removing `src/agents/code.py`
- Removing `agents/defs/code.md`
- Removing `src/mcp/tools/file_edit.py` (or removing the tool block from [`src/mcp_server.py`](src/mcp_server.py))
- Removing `/apply`, `/diff`, `/diffs`, `/show` commands from CLI
- Removing `code` agent configuration from `config.yaml`
- Deleting the `output/` directory entirely


## Consequences

### Positive
- Reduced maintenance burden (no file editing semantics to maintain)
- Clearer positioning: Agent Hub provides knowledge, not editing
- Simpler codebase (fewer agents to manage)
- Better alignment with MCP client capabilities (they handle editing better)



### Negative
- Users must use native IDE editing for file changes
- No standardized edit semantics across MCP clients
- Need to update client documentation to remove references to `file_edit`


### Neutral
- MCP `list_tools` no longer contains `file_edit`
- `python run.py --agent code` returns "unknown agent" error
- All traces of `/apply`, `/diff`, etc. removed from codebase


## Implementation Plan

1. Remove `src/agents/code.py` and `agents/defs/code.md`
2. Remove `file_edit` tool from [`src/mcp_server.py`](src/mcp_server.py)
3. Remove `code` agent registration from [`src/main.py`](src/main.py)
4. Remove `code` section from `config.yaml`
5. Remove `file_edit` from README's MCP tools table
6. Delete `output/` directory
7. Update any tests that reference removed code

## Related Decisions

- DECIDE-4: Remove `code` agent + `file_edit` MCP tool
- T-003: Execute removal

---

**See Also:**
- [T-003 — Remove `code` agent and `file_edit` MCP tool](T-003-remove-code-agent.md)
- [Phase 0 — Cleanup](../roadmap/00_MASTER_ROADMAP.md#phase-0--cleanup-1-week)
