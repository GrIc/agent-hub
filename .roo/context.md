# Agent Hub — Project Context

> Loaded on every call, every mode. Short reference.

---

## What Agent Hub is

A self-hosted **MCP server** that exposes a codebase's knowledge (semantic, structural, historical, conventional) to AI coding agents like Cline, Roo Code, Claude Code, Cursor, and Continue.dev.

It's **not** a chat app. It's **not** a code editor. It's a **knowledge broker** for other tools.

## Stack

| Concern | Choice |
|---------|--------|
| LLM serving | vLLM (OpenAI-compatible API) |
| Models | Mistral Small 4 119B (heavy), devstral-medium-2507 (code) |
| Embeddings | bge-m3 |
| Reranking | bge-reranker-large |
| Vector store | ChromaDB |
| Graph store | SQLite (see Phase 2) |
| Temporal store | SQLite (see Phase 3) |
| Web framework | FastAPI |
| Orchestration | Docker Compose (v2 syntax) |
| CI | Self-hosted GitLab |
| License | Apache 2.0 |
| Language | Python 3.11+ |

## Repo conventions

- `src/` — library code.
- `agents/defs/*.md` — agent definitions (system prompts).
- `config.yaml` — the only config file that matters.
- `web/` — FastAPI routes + HTML templates.
- `tests/` — pytest.
- `scripts/` — shell utilities (executable).
- `workspace/` — bind-mounted codebase being indexed. NOT under version control.
- `context/` — generated indexing artifacts (docs, graphs, quality reports). Gitignored.
- `docs/` — user-facing documentation.

## Important: CRLF vs LF

Workspaces are often bind-mounted from a **Windows host into a Linux container**. Files may contain CRLF line endings. Indexing must normalize `\r\n` → `\n` **before** chunking AND before hashing, or chunk IDs will differ between runs and force full re-indexing.

Always normalize bytes first:
```python
normalized = raw_bytes.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
```

## Important: `--bootstrap` after manual indexing

If you run a manual `/scan`, `synthesize.py`, or ingest: afterward run `python watch.py --bootstrap` to give the watch loop a clean baseline. Skipping this makes watch re-process everything on its next cycle.

## Common user workspaces

- Large Java codebases (CATIA / KPI / ENOVIA — Dassault Systèmes domain).
- Python services.
- Mixed mono-repos.

Expect 100k–10M LOC. Incremental indexing is mandatory.

## Current file layout (as of Phase 0 start)

```
agent-hub/
├── src/
│   ├── agents/         codex, documenter, expert, (Phase 0 removes: code, the 5 project agents)
│   ├── rag/            ingest, retrieval — Phase 1 hardens this
│   ├── mcp_server.py   Phase 4 replaces this with src/mcp/*
│   └── main.py
├── agents/defs/        <agent>.md per agent
├── web/
│   ├── server.py
│   ├── index.html      Phase 0 demotes to /debug/chat
│   └── ...
├── synthesize.py       Phase 1 hardens
├── build_graph.py      Phase 2 rewrites
├── watch.py            Phase 3 rewrites (changelog branch)
├── run.py
├── config.yaml
├── docker-compose.yml
└── Dockerfile
```

After Phases 0-2, expect new directories:
```
src/graph/              Phase 2
src/temporal/           Phase 3
src/mcp/                Phase 4
src/mcp/tools/          Phase 4 (23-29 files, one per tool)
src/pipelines/          Phase 5
```

## Before changing anything

- Read the task's CONTEXT section.
- Read the FILES listed.
- Read the `.roo/rules.md` if you haven't already this session.
- Read the relevant phase document (top of it is enough).
- If the task's Mode has a skill (see `.roo/skills/`), read the skill.

---

*End of context.*
