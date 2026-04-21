# Agent Hub

> The MCP server that gives AI coding agents senior-engineer-level knowledge of your codebase.

Works with **any OpenAI-compatible LLM API** — OpenAI, Mistral, vLLM, Ollama, LiteLLM, Azure OpenAI, or any provider that exposes `/v1/chat/completions`.


Uses **ChromaDB** for vector storage with optional cross-encoder reranking.

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

---

## Why

- Large codebases (100k–10M LOC) have knowledge in 5 layers (text, structure, semantics, conventions, history).
  Coding agents see only layer 1. Agent Hub exposes layers 2–5 as MCP tools.

## Quick start (5 commands)

1. clone
2. cp .env.example .env  # set API_KEY + API_BASE_URL
3. ln -s /path/to/your/code workspace
4. docker compose up -d
5. point your MCP client at http://localhost:8080/mcp/sse

## What you get

- 29 MCP tools across 8 categories (see [docs/mcp/tools.md](docs/mcp/tools.md), link)
- Auto-generated wiki at /wiki
- Daily changelog with semantic summaries
- Pattern & convention discovery
- Call graph + impact preview
- Custom YAML pipelines

## Documentation

- [Architecture](docs/architecture.md)
- [MCP tools reference](docs/mcp/tools.md)
- [Client setups](docs/clients/) — Cline, Roo, Claude Code, Cursor, Continue.dev
- [Operations](docs/operations/) — deploy, scale, troubleshoot
- [Decisions (ADRs)](docs/decisions/)
- [Roadmap](docs/roadmap/00_MASTER_ROADMAP.md)
