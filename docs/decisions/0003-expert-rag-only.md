# ADR 0003: Refocus `/v1/chat/completions` as `expert-rag` Model Only

## Status

Accepted

## Context

Agent Hub currently exposes multiple "models" via the OpenAI-compatible endpoint (`/v1/chat/completions`): `expert`, `documenter`, `codex`, etc. This creates confusion for clients about what Agent Hub actually is. Clients expect a model name that describes the capability, not an internal agent name.



The `/v1/chat/completions` endpoint is used by MCP clients like Roo Code for chat functionality. Exposing every internal agent as a "model" blurs the line between MCP tools and chat models.



## Decision

Keep the OpenAI-compatible endpoint but expose only one model name: `expert-rag`. This model name clearly communicates that Agent Hub provides RAG-augmented expert agent capabilities.



Internally, `expert-rag` uses the existing `expert` agent. Only the public-facing identifier changes; no refactoring of the agent itself is needed.


## Consequences

### Positive
- Clear, unambiguous model name that describes the capability
- Better alignment with MCP server positioning (tools, not multiple models)
- Simpler client configuration (only one model to configure)
- Reduced confusion about what Agent Hub provides



### Negative
- Clients must update their configuration to use `expert-rag` instead of `expert`, `documenter`, etc.
- Internal complexity: need to map `expert-rag` to `expert` agent


### Neutral
- `/v1/models` endpoint returns only `[{"id": "expert-rag", ...}]`
- Any other model name returns 404 `model_not_found`


## Implementation Plan

1. Update [`web/server.py`](web/server.py) to:
   - Make `/v1/models` return only `[{"id": "expert-rag", ...}]`
   - Make `/v1/chat/completions` accept only `model: "expert-rag"` (404 for others)
2. Update README and client setup instructions to use `expert-rag`
3. Update `continue-sse.yaml` and `continue-stdio.yaml` to use `expert-rag`
4. Update client documentation files in [`docs/clients/`](docs/clients/) to use `expert-rag`

## Related Decisions

- DECIDE-3: Keep `/v1/chat/completions` as expert-RAG only
- T-004: Execute refocusing

---

**See Also:**
- [T-004 — Refocus `/v1/chat/completions` as `expert-rag` model only](T-004-expert-rag-only.md)
- [Phase 0 — Cleanup](../roadmap/00_MASTER_ROADMAP.md#phase-0--cleanup-1-week)
