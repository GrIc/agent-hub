# Agent Hub

A **multi-agent system with RAG** for codebase understanding, documentation, and project management. CLI + web interface.

Works with **any OpenAI-compatible LLM API** — OpenAI, Mistral, vLLM, Ollama, LiteLLM, Azure OpenAI, or any provider that exposes `/v1/chat/completions`.

Uses **ChromaDB** for vector storage with optional cross-encoder reranking.

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

---

## Table of Contents

- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Warming Up: RAG Pipeline](#warming-up-rag-pipeline)
- [Web Interface](#web-interface)
- [CLI Usage](#cli-usage)
- [Agents](#agents)
- [Custom Agents](#custom-agents)
- [Project Pipeline](#project-pipeline)
- [Time-Travel Documentation](#time-travel-documentation)
- [IDE Integration](#ide-integration) (Roo Code, Continue.dev, Claude Code)
- [Docker Deployment](#docker-deployment)
- [CI/CD (GitLab)](#cicd-gitlab)
- [Project Structure](#project-structure)

---

## Quick Start

```bash
git clone https://github.com/youruser/agent-hub.git
cd agent-hub
pip install -r requirements.txt
cp .env.example .env          # Edit with your API credentials
```

### First run: index your codebase

```bash
# 1. Symlink or copy your codebase into workspace/
ln -s /path/to/your/code workspace

# Scan, synthesize, index
python run.py --agent codex --skip-ingest    # then: /scan
python synthesize.py                          # Build doc pyramid
python run.py --ingest                        # Index into RAG

# Run
python -m web.server                          # Web UI at :8080
python run.py --agent expert --skip-ingest    # CLI mode
```

---

## Configuration

Two files, clear separation:

| File | Contains | Versioned |
|---|---|---|
| `.env` | Secrets + environment (API keys, retry, Docker paths) | No (`.gitignore`) |
| `config.yaml` | Application config (models, agents, RAG, domain) | Yes |

### `.env` — Secrets & Environment

```bash
API_BASE_URL=https://api.openai.com/v1    # Any OpenAI-compatible endpoint
API_KEY=sk-...
WORKSPACE_PATH=./workspace
```

### `config.yaml`

```yaml
models:
  heavy: gpt-4o                    # Best reasoning model
  code: gpt-4o                     # Code-specialized
  light: gpt-4o-mini               # Fast/cheap
  embed: text-embedding-3-small    # Embeddings
  rerank: ""                       # Cross-encoder (optional)

agents:
  expert:
    model: code
    temperature: 0.3
  codex:
    model: heavy
    temperature: 0.3
```

Full configuration reference in [`config.yaml`](config.yaml) — every option is documented with comments.

### Domain customization

Agent Hub is **technology-agnostic**. If your codebase uses a domain-specific language or has specific business context, configure it in `config.yaml`:

```yaml
# Your custom DSL (optional)
custom_dsl:
  name: "HQL"
  description: "Hibernate Query Language for database queries."

# Business domain (optional)
domain:
  sector: "fintech"
  product_type: "lending platform"
  glossary:
    - term: "RiskScore"
      definition: "Credit score 0-1000"
```

This context is injected into all agent prompts automatically.

---

## Warming Up: RAG Pipeline

Agent Hub builds a **dynamic documentation pyramid** from your code:

```
L0  Architecture Overview          (1 file — the big picture)
L1+ Intermediate Layers            (depends on code hierarchy depth)
    Examples: L1_backend.md, L2_backend_api.md, L3_backend_api_routes.md, ...
    Level numbering is dynamic: deep hierarchies may reach L11+ before L0
L3  Per-file Documentation         (1 per source file: codex_*.md)
    Raw Source Code                 (chunked workspace files)
```

**How synthesis works:**
- **Codex** generates L3 docs (one per file) and classifies them into blocks (backend, frontend, database, infrastructure, etc.)
- **Synthesize** aggregates bottom-up within each block:
  - L3 (files) → L2 (packages) → L1 (modules) → ... → L0 (architecture)
  - The depth of intermediate levels depends on your code structure
- Each level condenses docs to focus on key components and dependencies

### Step-by-step

```bash
# 1. CODEX: Scan workspace, generate L3 docs
python run.py --agent codex --skip-ingest
> /scan                          # Scans all files, generates context/docs/codex_*.md

# 2. SYNTHESIZE: Build the doc pyramid (bottom-up aggregation)
python synthesize.py             # Bottom-up: L3 → intermediate layers → L0
python synthesize.py --dry-run   # Preview without generating
python synthesize.py --force     # Rebuild everything

# 3. INGEST: Index into ChromaDB
python run.py --ingest           # Index context/ + workspace/ + reports/
python run.py --clear-index      # Delete and rebuild from scratch

# 4. WATCH: Incremental updates (detect changes, re-document, update RAG)
python watch.py                  # Process changed files since last run
python watch.py --status         # Show what would change
python watch.py --reset          # Clear state, next run processes everything
```

### Hierarchical search

When an agent queries the RAG, the system does:
1. **Pass 1**: Search synthesis docs (L0, L1, L2, ...) for architectural context
2. **Pass 2**: Search detailed docs (L3, code) for implementation specifics
3. **Rerank**: Cross-encoder reranking on each pass (if configured)
4. **Merge**: Deduplicate and sort by relevance

This ensures architecture questions get high-level answers while code questions get implementation details.

---

## Web Interface

Agent Hub has three web pages, all served by the same FastAPI server:

```bash
python run.py --agent codex -s    # Scan workspace → L3 docs
python synthesize.py              # Build L2 → L1 → L0 (bottom-up)
python run.py --ingest            # Index everything into ChromaDB
```

### Incremental updates

```bash
python run.py                                      # Interactive agent menu
python run.py --agent specifier --project my-feat   # Direct agent + project
python run.py --agent expert --skip-ingest          # Skip indexing
python run.py --ingest                              # Index-only mode
python run.py --clean                               # Delete index + outputs
```

### Global commands (available in all agents)

| Command | Description |
|---|---|
| `/help` | Show available commands |
| `/save` | Summarize session and save as a report |
| `/reports` | List saved reports |
| `/undo` | Delete the last report |
| `/history` | Show recent conversation history |
| `/clear` | Clear conversation history |
| `/switch` | Switch to another agent |
| `/reindex` | Re-index documents into RAG |
| `/pipeline` | Start the project pipeline |
| `/pipeline status` | Show pipeline progress |
| `/pipeline from specifier` | Resume from a specific step |
| `/quit` | Exit |

### Project commands (project-scoped agents only)

| Command | Description |
|---|---|
| `/load` | Load project notes and upstream documents |
| `/status` | Project overview (notes, outputs, reports) |
| `/draft` | Generate a draft document |
| `/finalize` | Generate final version |
| `/alternative` | Propose a radically different approach |
| `/versions [type]` | List all versions of a document |
| `/rollback [type] N` | Rollback to version N |

---

## Agents

### Core agents

| Agent | Scope | Purpose |
|---|---|---|
| **expert** | global | Code Q&A, review, debug — primary dev assistant |
| **codex** | global | Scan codebase → generate documentation for RAG |
| **documenter** | global | Architecture docs & Mermaid diagrams |
| **code** | global | Generate `git diff` files for implementation |
| **portfolio** | project | Raw notes → requirements |
| **specifier** | project | Requirements → technical specifications + architecture |
| **planner** | project | Specs → roadmap with tasks and estimates |
| **storyteller** | project | All docs → techno-functional synthesis |
| **presenter** | project | Synthesis → 10-slide deck plan |

### Agent-specific commands

**Codex**: `/scan [path]`, `/inventory`, `/tree`
**Code**: `/apply` (git apply), `/diff`, `/diffs`, `/show <file>`, `/tree`
**Documenter**: `/overview`, `/classes [module]`, `/sequence [flow]`, `/datamodel`, `/components`, `/reference [module]`

---

## Custom Agents

Create a `.md` file in `agents/defs/` — no Python code needed:

```markdown
# Agent: Reviewer

## Config
- scope: global
- web: yes
- emoji: 🔍
- description: Code review assistant

## Role
You are a senior code reviewer...

## Linked agents
- **expert**: can answer questions about code behavior
```

That's it. The agent appears in the CLI menu and web UI automatically. See [config reference](README.md#custom-agent-config) below.

### Custom agent config reference

| Key | Values | Default | Description |
|---|---|---|---|
| `scope` | `global` / `project` | `global` | Project agents require `--project` and get versioned outputs |
| `web` | `yes` / `no` | `no` | Show in web UI |
| `emoji` | any emoji | 🤖 | Menu display |
| `description` | text | — | One-line description |
| `model` | model alias | `heavy` | From `config.yaml` models section |
| `temperature` | 0.0–1.0 | 0.5 | LLM temperature |
| `doc_type` | text | — | (project) Document type for versioning |
| `output_tag` | text | — | (project) Fenced block tag for auto-save |
| `upstream_types` | comma-list | — | (project) Which upstream docs to load |

---

## Project Pipeline

The pipeline automates the full project workflow:

```
notes/ → portfolio → specifier → planner → storyteller → presenter → code
         (requirements) (specs)    (roadmap) (synthesis)    (deck)      (diffs)
```

### Using the pipeline

**CLI**:
```bash
# CLI
python run.py --project my-feature --skip-ingest
> /pipeline                      # Start from the beginning
> /pipeline from specifier       # Resume from a step
> /pipeline status               # Show progress
```

**Web** (at `/workspace`):
1. Select or create a project
2. Click **▶ Pipeline**
3. At each step: chat with the agent, use `/load`, `/draft`
4. Click **✅ Finalize** to advance, **⏭ Skip** to skip, **✖ Abort** to stop

Each step produces versioned outputs (`requirements_v1.md`, `specifications_v2.md`, etc.) in `projects/{name}/outputs/`. Use `/finalize` to advance, `/rollback N` to revert.

---

## Time-Travel Documentation

Every time `watch.py` detects code changes, it generates a narrative changelog entry:

> "Today the team refactored the authentication module to use JWT tokens.
> This impacts the UserService and AuthMiddleware components..."

Stored in `context/changelog/YYYY-MM-DD.md`. Viewable at `/docs` → Changelog tab.

---

## IDE Integration

Agent Hub exposes two complementary interfaces once deployed:

| Interface | URL | Use case |
|-----------|-----|----------|
| **Open WebUI** | `http://localhost:3000` | Chat UI with hybrid search (RAG + GraphRAG) |
| **Chat API** | `http://localhost:8080/v1` | Any OpenAI-compatible client (Roo Code, Cursor, etc.) |
| **MCP tools** | `http://localhost:8080/mcp/sse` | Agent Hub tools in IDE agent mode |

### Architecture

```
 VS Code / IntelliJ / Cursor            Your browser
 ┌──────────────────────────┐          ┌───────────────┐
 │  Roo Code / Continue.dev │          │  Open WebUI   │
 └────────────┬─────────────┘          └──────┬────────┘
              │                               │
    ┌─────────┴──────────┐                    │
    │  MCP SSE (tools)   │  OpenAI API        │
    │  /mcp/sse          │  /v1/chat/         │
    │                    │  completions       │
    └─────────┬──────────┘                    │
              │                               │
 ┌────────────┴───────────────────────────────┴────────┐
 │                  Agent Hub  :8080                   │
 │                                                     │
 │   /v1/chat/completions ──► RAG + GraphRAG + LLM     │
 │   /mcp/sse             ──► expert_ask, search_rag…  │
 │   /api/ask             ──► Web UI internal          │
 ├─────────────────────────────────────────────────────┤
 │   ChromaDB (.vectordb) │  KnowledgeGraph (.graphdb) │
 └─────────────────────────────────────────────────────┘
```

### Setup: Open WebUI

**1. Start all services**

```bash
docker compose -f docker-compose.yml -f docker-compose.ide.yml up -d
```

Open WebUI is at `http://localhost:3000`.

On first visit, create your admin account. Open WebUI is already pre-configured:
- **Model**: `expert` (Agent Hub expert agent with hybrid search)
- **API**: points to Agent Hub `/v1/*` — every message goes through RAG + GraphRAG
- Switch models from the dropdown to use any other agent (`documenter`, `specifier`, etc.)

No additional configuration needed.

---

### Setup: Roo Code

Roo Code connects to Agent Hub for both **chat** (hybrid search) and **tools** (MCP).

**1. Install Roo Code**

Install the [Roo Code extension](https://marketplace.visualstudio.com/items?itemName=RooVeterinaryInc.roo-cline) from the VS Code marketplace.

**2. Configure the LLM provider**

In Roo Code settings, add a custom OpenAI-compatible provider:

| Field | Value |
|-------|-------|
| Provider | OpenAI Compatible |
| Base URL | `http://localhost:8080/v1` |
| API Key | *(your `API_KEY` from `.env`)* |
| Model | `expert` |

Every chat message will go through Agent Hub's full hybrid search pipeline.

**3. Configure MCP tools**

Add this to your Roo Code MCP config (`.roo/mcp.json` or via Settings → MCP Servers):

```json
{
  "mcpServers": {
    "agent-hub": {
      "type": "sse",
      "url": "http://localhost:8080/mcp/sse"
    }
  }
}
```

Roo Code can now call Agent Hub tools during agentic tasks:
- `expert_ask` — RAG-powered code Q&A
- `search_rag` — Search the vector index directly
- `search_graph` — Entity relationships and dependency queries
- `read_file` / `edit_file` — Browse and edit workspace files
- `list_deliverables` / `read_deliverable` / `apply_deliverable` — Project deliverables

---

### Setup: Continue.dev

Continue.dev connects to Agent Hub for **tools** (MCP) in Agent mode. For chat, configure it as an OpenAI-compatible provider the same way as Roo Code above.

**1. Install Continue**

- VS Code: search "Continue" in the Extensions marketplace
- JetBrains: search "Continue" in the JetBrains Marketplace

**2. Configure MCP tools**

```bash
mkdir -p .continue/mcpServers
cp continue-sse.yaml .continue/mcpServers/agent-hub.yaml
```

The `continue-sse.yaml` file at the root of this repo is ready to use. It points to `http://localhost:8080/mcp/sse`.

If Agent Hub runs on a different host or port, edit the `url` field in the copied file.

**3. Configure the chat provider** *(optional)*

In `.continue/config.yaml`:

```yaml
models:
  - title: Agent Hub — Expert
    provider: openai
    model: expert
    apiBase: http://localhost:8080/v1
    apiKey: <your API_KEY>
  - title: Agent Hub — Documenter
    provider: openai
    model: documenter
    apiBase: http://localhost:8080/v1
    apiKey: <your API_KEY>
```

**4. Using Agent mode**

1. Open the Continue sidebar
2. Switch to **Agent** mode (tools only work in Agent mode, not Chat)
3. Agent Hub tools are available automatically:
   - *"Use expert_ask to explain the authentication module"*
   - *"Search the RAG index for database migration patterns"*
   - *"List deliverables for project my-feature"*

Continue.dev works in VS Code, IntelliJ, PyCharm, WebStorm, and all JetBrains IDEs.

---

### Setup: Claude Code

Claude Code (the Anthropic CLI) connects to Agent Hub via MCP in two modes.

#### Mode SSE (Agent Hub running as a server)

Add this to your `~/.claude/settings.json` (global) or `.claude/settings.json` (project):

```json
{
  "mcpServers": {
    "agent-hub": {
      "type": "sse",
      "url": "http://localhost:8080/mcp/sse"
    }
  }
}
```

Prerequisites: Agent Hub must be running (`docker compose up` or `python -m web.server`).

#### Mode stdio (Agent Hub spawned as a subprocess)

Claude Code spawns `python -m src.mcp_server` directly. No web server needed.

Add this to your `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "agent-hub": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "src.mcp_server"],
      "cwd": "/path/to/agent-hub",
      "env": {
        "PYTHONPATH": "/path/to/agent-hub"
      }
    }
  }
}
```

A ready-to-use config file is provided at the root of this repo: copy `claude-code-mcp.json` into `~/.claude/settings.json` (or merge the `mcpServers` block into your existing settings) and adjust the `cwd` path.

#### Using Agent Hub tools in Claude Code

Once configured, Claude Code can call Agent Hub tools in any agentic session:

```
> Use expert_ask to explain how the authentication module works
> Search the RAG index for database migration patterns
> What does search_graph say about dependencies of UserService?
> List deliverables for project my-feature and apply the latest spec
```

---

### Available MCP tools

| Tool | Description |
|------|-------------|
| `expert_ask` | RAG-powered code Q&A with full hybrid search |
| `search_rag` | Search the vector index directly (returns raw chunks + scores) |
| `search_graph` | Query the knowledge graph for entity relationships and dependencies |
| `read_file` | Read a file from the workspace |
| `edit_file` | Write/overwrite a file in the workspace |
| `list_deliverables` | List project deliverables (specs, roadmaps…) |
| `read_deliverable` | Read a specific deliverable's content |
| `apply_deliverable` | Apply a deliverable automatically (dry-run or live) |

---

## Web Interface

```bash
python -m web.server                   # http://localhost:8080
```

### Expert (`/`)

Chat interface for quick code Q&A. Highlight.js syntax coloring, Mermaid diagrams, copy buttons.

### Workspace (`/workspace`)

3-panel interface for the full pipeline experience:

```
┌──────────┬────────────────────┬──────────────────┐
│ 📁 Files │   💬 Conversation  │   📄 Preview     │
│ tree     │   /commands work   │   md + mermaid   │
└──────────┴────────────────────┴──────────────────┘
```

### Docs Hub (`/docs`)

Documentation browser with three tabs: **Pyramid** (architecture overview + synthesis docs), **RAG Coverage** (which files are indexed), **Changelog** (time-travel). The pyramid shows L0 (architecture) down through generated synthesis layers, organized by block (backend, frontend, database, infrastructure, etc.).

---

## Docker Deployment

### Services

Agent Hub has **two deployment modes**:

**Web-only** (`docker-compose.yml`):
| Container | Purpose |
|---|---|
| `agent-hub-web` | Web UI (expert + workspace + docs) on port 8080 |
| `agent-hub-indexer` | Periodic indexer (watch → synthesize → ingest) |

**With IDE integration** (add `docker-compose.ide.yml`):
| Container | Purpose |
|---|---|
| `agent-hub-web` | Web UI + `/v1/*` API + MCP SSE on port 8080 |
| `agent-hub-indexer` | Periodic indexer (watch → synthesize → ingest) |
| `open-webui` | Chat frontend for Agent Hub on port 3000 |

### Setup

```bash
cp .env.example .env             # Edit credentials

# Web-only (no IDE integration)
./scripts/deploy.sh setup        # First-time setup
docker compose up -d             # Start services

# With IDE integration
docker compose -f docker-compose.yml -f docker-compose.ide.yml up -d
```

### Volumes & Persistence

All services share the same volumes:
- `workspace/` — your codebase (read-only for web, read-write for indexer)
- `context/` — generated docs (updated by indexer)
- `projects/` — project data (updated by agents)
- `.vectordb/` — ChromaDB index (shared by web + agents)

The indexer auto-generates documentation (`/scan`, `synthesize`, `/ingest`) on a schedule. The web and IDE tools consume the pre-built index.

### Management

```bash
./scripts/deploy.sh update       # Pull latest + restart
./scripts/deploy.sh status       # Service status + API stats
./scripts/deploy.sh logs         # Tail logs
./scripts/deploy.sh restart      # Restart services
./scripts/deploy.sh stop         # Stop services
./scripts/deploy.sh reset-index  # Clear index and restart
```

### Viewing logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f web       # Agent Hub web
docker compose logs -f indexer   # Indexer
docker compose logs -f open-webui  # Open WebUI
```

---

## CI/CD (GitLab)

The `.gitlab-ci.yml` builds a Docker image and pushes to your registry on each push to `main`.

### Required CI/CD Variables

| Variable | Description |
|---|---|
| `REGISTRY_URL` | Docker registry URL |
| `REGISTRY_USER` | Registry username |
| `REGISTRY_PASSWORD` | Registry password |
| `DEPLOY_HOST` | Target machine hostname (for auto-deploy) |
| `DEPLOY_USER` | SSH user on target |
| `DEPLOY_SSH_KEY_B64` | Base64-encoded SSH key |
| `DEPLOY_PATH` | Path to the cloned repo on target |

Deploy is manual (`when: manual` in the pipeline).

---

## Project Structure

```
agent-hub/
├── .env.example              ← Secrets & environment template
├── config.yaml               ← Models, agents, RAG, domain config
├── run.py                    ← CLI entry point
├── synthesize.py             ← Hierarchical doc synthesis (dynamic L0→LN based on code depth)
├── watch.py                  ← Incremental change detection + changelog
├── Dockerfile                ← Docker image
├── docker-compose.yml        ← Web + indexer services
│
├── agents/defs/              ← Agent definitions (core + custom, all Markdown)
│   ├── expert.md ... presenter.md
│   └── your-custom-agent.md
│
├── context/                  ← RAG context (global)
│   ├── docs/                 ← Generated by codex (/scan) + synthesize.py
│   │   ├── codex_*.md        ← Per-file docs (L3: one per source file)
│   │   └── synthesis/        ← Dynamic pyramid (L0 architecture + intermediate layers)
│   │       ├── L0_ARCHITECTURE_OVERVIEW.md
│   │       ├── L1_backend_OVERVIEW.md
│   │       ├── L2_backend_api.md
│   │       └── ...up to LN based on your code hierarchy depth
│   ├── architecture/         ← Manual architecture notes
│   ├── code-samples/         ← Manual code examples
│   └── changelog/            ← Time-travel entries (YYYY-MM-DD.md)
│
├── projects/                 ← Project-scoped data
│   └── {name}/
│       ├── notes/            ← Raw input (meeting minutes, PDFs)
│       ├── outputs/          ← Versioned outputs (requirements_v1.md, ...)
│       └── reports/          ← Per-agent session reports
│
├── workspace/                ← Your codebase (symlink or copy)
│
├── src/                      ← Python source
│   ├── main.py               ← CLI app + chat loop
│   ├── client.py             ← Resilient API client (retry + rerank)
│   ├── config.py             ← .env + config.yaml loader
│   ├── agent_defs.py         ← Markdown agent definition parser
│   ├── projects.py           ← Project isolation + versioning
│   ├── reports.py            ← Inter-agent report system
│   ├── pipeline.py           ← Pipeline orchestrator
│   ├── changelog.py          ← Time-travel changelog generator
│   ├── workspace_session.py  ← Web workspace session manager
│   ├── agents/               ← Core agent implementations
│   │   ├── base.py           ← BaseAgent (prompt, RAG, reports)
│   │   ├── project_agent.py  ← ProjectAgent (versioning, /load)
│   │   ├── codex.py          ← Codebase scanner
│   │   ├── code.py      ← Git diff generator
│   │   ├── documenter.py     ← Architecture documentation
│   │   ├── portfolio.py      ← Requirements from notes
│   │   ├── specifier.py      ← Technical specifications
│   │   ├── planner.py        ← Roadmap + tasks
│   │   ├── storyteller.py    ← Techno-functional synthesis
│   │   └── presenter.py      ← Slide deck planning
│   └── rag/
│       ├── ingest.py         ← Document parsing + chunking
│       └── store.py          ← ChromaDB wrapper + hierarchical search
│
├── web/
│   ├── server.py             ← FastAPI app (all routes)
│   ├── ide_routes.py         ← IDE integration REST fallback routes
│   ├── workspace_routes.py   ← /workspace API routes
│   ├── docs_routes.py        ← /docs API routes
│   ├── index.html            ← Expert chat UI
│   ├── workspace.html        ← 3-panel workspace UI
│   └── docs.html             ← Documentation Hub UI
│
├── src/
│   └── mcp_server.py         ← MCP server for IDE integration (7 tools)
│
├── docker-compose.ide.yml    ← Open WebUI service (optional)
├── continue-sse.yaml         ← Continue.dev / Roo Code MCP config (copy into your project)
├── continue-stdio.yaml       ← Continue.dev MCP config (local dev, no Docker)
├── claude-code-mcp.json      ← Claude Code MCP config (merge into ~/.claude/settings.json)
│
└── scripts/
    ├── deploy.sh             ← Docker management helper
    └── indexer-loop.sh       ← Indexer entrypoint (watch→synthesize→ingest)
```

---

## License

[Apache License 2.0](LICENSE) — free for commercial use, provides patent protection.