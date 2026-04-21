# ADR 0002: Demote `/` Chat to `/debug/chat`

## Status

Accepted

## Context

The home-page chat at `/` competes with Open WebUI (already integrated) and confuses users about Agent Hub's purpose. Keeping it as the front door dilutes our positioning as an MCP server and creates ambiguity: "Should I use the in-repo chat or Open WebUI?"


The debug chat has value for inspecting retrieval results and source citations, but doesn't belong on the home page.


## Decision

Demote the chat interface from `/` to `/debug/chat`. The debug chat becomes a tool for inspecting retrieval results and source citations, not a primary user interface.


Add a redirect from `/` to `/admin` (placeholder page delivered in T-005) to guide users to the correct interfaces.

## Consequences

### Positive
- Clear separation: MCP tools for IDE integration, debug chat for source citation inspection
- Reduced user confusion about which interface to use
- Better alignment with our MCP server positioning
- Open WebUI remains the recommended chat frontend


### Negative
- Users must learn new URL (`/debug/chat` instead of `/`)
- Need to maintain `/admin` placeholder page
- Debug chat has less discoverability

### Neutral
- Debug chat gains expanded source citation display (file path, line range, doc level, click-to-expand snippet)
- Web UI banner clarifies purpose: "Debug UI — for daily chat use Open WebUI at :3000"


## Implementation Plan

1. Change route in [`web/server.py`](web/server.py) from `/` to `/debug/chat`
2. Add redirect from `/` to `/admin`
3. Update [`web/index.html`](web/index.html) with banner explaining debug chat purpose
4. Update README to reference Open WebUI instead of in-repo chat
5. Ensure debug chat shows expanded source citations

## Related Decisions

- DECIDE-2: Demote `/` chat to `/debug/chat`
- T-002: Execute demotion

---

**See Also:**
- [T-002 — Demote `/` chat to `/debug/chat`](T-002-demote-chat.md)
- [Phase 0 — Cleanup](../roadmap/00_MASTER_ROADMAP.md#phase-0--cleanup-1-week)
