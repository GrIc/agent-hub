# Agent Hub

A **multi-agent system with RAG** for codebase understanding, documentation, and project management. CLI + web interface.

Works with **any OpenAI-compatible LLM API** — OpenAI, Mistral, vLLM, Ollama, LiteLLM, Azure OpenAI, or any provider that exposes `/v1/chat/completions`.

Uses **ChromaDB** for vector storage with optional cross-encoder reranking.

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

---

## What it does

Agent Hub gives your development team **AI agents that actually know your codebase**. Instead of generic LLM answers, every response is grounded in your indexed code through RAG — no hallucination.

**9 core agents** work together through a pipeline:

```
notes/ → portfolio → specifier → planner → storyteller → presenter → developer
         (requirements) (specs)    (roadmap) (synthesis)    (deck)      (diffs)
```

Plus an always-on **expert** agent for daily code Q&A, review, and debugging.

**3 web interfaces**:

| Page | URL | Purpose |
|---|---|---|
| Expert | `/` | Quick code Q&A with any agent |
| Workspace | `/workspace` | Full pipeline with 3-panel UI (file tree, chat, preview) |
| Docs Hub | `/docs` | Browse documentation pyramid, RAG coverage, changelog |

Everything runs on your infrastructure. Your code never leaves your network.

---

## Quick Start

```bash
git clone https://github.com/GrIc/agent-hub.git
cd agent-hub
pip install -r requirements.txt
cp .env.example .env          # Edit with your API credentials
```

```bash
# Point to your codebase
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

| File | Contains | In `.gitignore` |
|---|---|---|
| `.env` | API keys, retry settings, Docker paths | Yes |
| `config.yaml` | Models, agents, RAG, domain config | No |

### `.env`

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

## RAG Pipeline

Agent Hub builds a **documentation pyramid** from your code:

```
L0  Architecture Overview          (1 file — the big picture)
L1  Layer Overviews                (backend, frontend, database, etc.)
L2  Module Documentation           (grouped by package)
L3  Per-file Documentation         (1 per source file)
    Raw Source Code                 (chunked workspace files)
```

### Build the pyramid

```bash
python run.py --agent codex -s    # Scan workspace → L3 docs
python synthesize.py              # Build L2 → L1 → L0 (bottom-up)
python run.py --ingest            # Index everything into ChromaDB
```

### Incremental updates

```bash
python watch.py                   # Detect changes, re-document, update RAG
python watch.py --status          # Show what would change
```

The Docker indexer runs this automatically on a schedule.

### Hierarchical search

When an agent queries the RAG:
1. **Pass 1**: Search synthesis docs (L0-L2) for architecture context
2. **Pass 2**: Search detailed docs (L3, code) for implementation details
3. **Rerank**: Cross-encoder reranking (if configured)
4. **Merge**: Deduplicate and return top results

---

## Agents

### Core agents

| Agent | Scope | Purpose |
|---|---|---|
| **expert** | global | Code Q&A, review, debug — primary dev assistant |
| **codex** | global | Scan codebase → generate documentation for RAG |
| **documenter** | global | Architecture docs & Mermaid diagrams |
| **developer** | global | Generate `git diff` files for implementation |
| **portfolio** | project | Raw notes → requirements |
| **specifier** | project | Requirements → technical specifications + architecture |
| **planner** | project | Specs → roadmap with tasks and estimates |
| **storyteller** | project | All docs → techno-functional synthesis |
| **presenter** | project | Synthesis → 10-slide deck plan |

### Custom agents (no code needed)

Drop a Markdown file in `agents/defs/`:

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

## Pipeline

The project pipeline automates the full workflow from notes to implementation:

```bash
# CLI
python run.py --project my-feature --skip-ingest
> /pipeline                      # Start from beginning
> /pipeline from specifier       # Resume from a step
> /pipeline status               # Show progress
```

**Web** (at `/workspace`): select a project, click **▶ Pipeline**, follow the step-by-step flow.

Each step produces versioned outputs (`requirements_v1.md`, `specifications_v2.md`, etc.). Use `/finalize` to advance, `/rollback N` to revert.

---

## Time-Travel Documentation

Every time `watch.py` detects code changes, it generates a narrative changelog entry:

> "Today the team refactored the authentication module to use JWT tokens.
> This impacts the UserService and AuthMiddleware components..."

Stored in `context/changelog/YYYY-MM-DD.md`. Viewable at `/docs` → Changelog tab.

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

Documentation browser with three tabs: **Pyramid** (L0→L3 docs), **RAG Coverage** (which files are indexed), **Changelog** (time-travel).

---

## Docker Deployment

```bash
cp .env.example .env             # Edit credentials
./scripts/deploy.sh setup        # First-time setup
docker compose up -d             # Start web + indexer
```

| Container | Purpose |
|---|---|
| `agent-hub-web` | Web UI on port 8080 |
| `agent-hub-indexer` | Periodic watch → synthesize → ingest |

```bash
./scripts/deploy.sh status       # Service status
./scripts/deploy.sh logs         # Tail logs
./scripts/deploy.sh update       # Pull + restart
```

---

## CI/CD (GitLab)

The `.gitlab-ci.yml` builds a Docker image on push to `main` and optionally deploys via SSH.

Required CI/CD variables: `REGISTRY_URL`, `REGISTRY_USER`, `REGISTRY_PASSWORD`.
Optional (auto-deploy): `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY_B64`, `DEPLOY_PATH`.

---

## Project Structure

```
agent-hub/
├── .env.example              ← API credentials template
├── config.yaml               ← Models, agents, RAG, domain
├── run.py                    ← CLI entry point
├── synthesize.py             ← Doc pyramid builder
├── watch.py                  ← Incremental change detection
├── agents/defs/              ← Agent definitions (Markdown)
├── context/                  ← RAG context
│   ├── docs/                 ← Generated docs (codex + synthesis)
│   └── changelog/            ← Time-travel entries
├── projects/                 ← Project data (notes, outputs, reports)
├── workspace/                ← Your codebase (symlink)
├── src/                      ← Python source
│   ├── agents/               ← Agent implementations
│   ├── rag/                  ← Ingestion + vector store
│   ├── pipeline.py           ← Pipeline orchestrator
│   └── changelog.py          ← Time-travel generator
├── web/                      ← Web UI (FastAPI + HTML)
└── scripts/                  ← Docker deployment helpers
```

---

## Requirements

- Python 3.12+
- Any OpenAI-compatible LLM API
- ChromaDB (installed via pip, no external server needed)

---

## License

[Apache License 2.0](LICENSE) — free for commercial use, provides patent protection.