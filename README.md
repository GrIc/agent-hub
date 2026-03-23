# Agent Hub

A **multi-agent CLI + web system with RAG** (Retrieval-Augmented Generation) for codebase understanding, documentation, and project management.

Works with any **OpenAI-compatible LLM API** (OpenAI, Mistral, vLLM, Ollama, LiteLLM, etc.) and uses **ChromaDB** for vector storage.

## What it does

Agent Hub provides **9 core agents** that work together on your codebase, plus support for **custom agents** defined entirely in Markdown.

### Core agents

| Agent | Scope | Web | Purpose |
|---|---|---|---|
| **expert** | global | yes | Code Q&A for colleagues (read-only) |
| **codex** | global | no | Scan codebase → generate docs for RAG |
| **documenter** | global | yes | Architecture docs & Mermaid diagrams |
| **developer** | global | no | Implement tasks, modify code in workspace |
| **portfolio** | project | yes | Raw notes → `requirements_vN.md` |
| **specifier** | project | yes | Requirements → `specifications_vN.md` |
| **planner** | project | yes | Specs → `roadmap_vN.md` |
| **architect** | project | yes | Specs + roadmap → `architecture_vN.md` |
| **presenter** | project | yes | All docs → `deck_vN.md` |

Core agents have dedicated Python classes with special commands (`/scan`, `/apply`, `/diff`, etc.).

### Custom agents

Drop a `.md` file in `agents/defs/` and it becomes an agent automatically. No Python code needed. See [Custom Agents](#custom-agents) below.

## Quick Start

```bash
git clone https://github.com/youruser/agent-hub.git
cd agent-hub
pip install -r requirements.txt
cp .env.example .env   # Edit with your API endpoint and key
```

```bash
python run.py --skip-ingest --agent developer     # Verify API works
python run.py --skip-ingest --agent codex          # Scan codebase
python synthesize.py                                # Build doc pyramid
python run.py --ingest                              # Index into RAG
python run.py --agent specifier --project my-feat   # Use project agents
python -m web.server                                # Web UI at :8080
```

## Custom Agents

### Creating a custom agent

Create a Markdown file in `agents/defs/`, for example `agents/defs/reviewer.md`:

```markdown
# Agent: Reviewer

## Config
- scope: global
- web: yes
- emoji: 🔍
- description: Code review assistant
- model: heavy
- temperature: 0.3

## Role
You are a senior code reviewer. You analyze code from the RAG context
and provide constructive feedback on quality, patterns, and potential bugs.

## Behavior
- Focus on actionable feedback
- Cite specific files from the RAG context
- Categorize findings: bugs, performance, security, maintainability

## Linked agents
- **expert**: can answer questions about code behavior
- **developer**: can implement your suggestions
```

That's it. The agent appears in the CLI menu and in the web UI (because `web: yes`).

### Config reference

The `## Config` section supports these keys:

| Key | Values | Default | Description |
|---|---|---|---|
| `scope` | `global` / `project` | `global` | `project` agents require `--project <name>` and get versioned outputs |
| `web` | `yes` / `no` | `no` | Whether the agent appears in the web UI |
| `emoji` | any emoji | 🤖 | Displayed in menus |
| `description` | text | agent name | One-line description for menus |
| `model` | model alias | `heavy` | Model alias from `config.yaml` (e.g., `heavy`, `code`, `light`, `reasoning`) |
| `temperature` | 0.0 - 1.0 | 0.5 | LLM temperature |

For **project-scoped** custom agents, these additional keys are available:

| Key | Example | Description |
|---|---|---|
| `doc_type` | `analysis` | Document type name (used for versioned filenames like `analysis_v1.md`) |
| `output_tag` | `analysis_md` | Tag the LLM wraps output in (` ```analysis_md ``` `) for auto-save |
| `upstream_types` | `requirements, specifications` | Which upstream docs to load as context (comma-separated) |

### Example: project-scoped custom agent

```markdown
# Agent: Tester

## Config
- scope: project
- web: yes
- emoji: 🧪
- description: Generate test plans from specifications
- model: heavy
- temperature: 0.3
- doc_type: testplan
- output_tag: testplan_md
- upstream_types: requirements, specifications

## Role
You are a QA engineer. You read specifications and produce comprehensive test plans.

## Output format
Wrap test plans with ```testplan_md and ```.

## Linked agents
- **specifier**: provides the specifications you're testing
- **planner**: provides the roadmap for test scheduling
```

This agent will:
- Appear in the CLI and web UI
- Require `--project <name>` to run
- Auto-load latest `requirements` and `specifications` from project outputs
- Auto-save output as `testplan_v1.md`, `testplan_v2.md`, etc.
- Support `/load`, `/draft`, `/finalize`, `/versions`, `/rollback` commands

### How it works

Core agents (codex, developer, documenter, etc.) have Python classes with special `/commands`. Custom agents use `BaseAgent` (global) or `ProjectAgent` (project) automatically — they get all the standard commands (`/save`, `/reports`, `/help`, `/load`, `/draft`, `/finalize` for project scope) but not the specialized ones like `/scan` or `/apply`.

The `## Config` and `## Linked agents` sections are parsed as metadata and **removed** from the system prompt. Everything else in the `.md` becomes the agent's system prompt.

## Project Structure

```
agent-hub/
├── .env.example          ← API credentials, paths
├── config.yaml           ← Models, RAG, custom DSL, synthesis blocks
├── run.py                ← CLI entry point
├── synthesize.py         ← Hierarchical doc synthesis (L0/L1/L2)
├── watch.py              ← Incremental change detection + RAG update
├── agents/defs/          ← Agent definitions (core + custom, all Markdown)
│   ├── expert.md ... presenter.md   ← Core agents
│   └── your-agent.md               ← Your custom agents
├── context/              ← RAG context (docs, architecture notes, code samples)
├── projects/             ← Project-scoped data (notes → outputs)
├── workspace/            ← Your codebase (symlink or copy)
├── src/                  ← Python source
│   ├── main.py, client.py, config.py
│   ├── agents/           ← Core agent implementations
│   └── rag/              ← Ingestion + vector store
├── web/server.py         ← FastAPI web UI
└── scripts/              ← Docker deployment helpers
```

## Configuration

### Models

Edit `config.yaml` to set your models:

```yaml
models:
  heavy: gpt-4o
  code: gpt-4o
  light: gpt-4o-mini
  embed: text-embedding-3-small
```

### Custom DSL

If your codebase uses a domain-specific language, describe it in `config.yaml`. This context is injected into all agent prompts:


### Custom SCM

```yaml
scm:
  unlock_cmd: "p4 edit {filepath}"
  lock_cmd: "p4 revert -a {filepath}"
```

### Synthesis blocks

Customize how `synthesize.py` classifies codex docs:

```yaml
synthesis:
  blocks:
    database:
      label: "Database / SQL"
      path_patterns: [".sql", "/reffiles/", "/ddl/"]
    frontend:
      path_patterns: ["/js/", "/ts/"]
```

## Docker Deployment

```bash
./scripts/deploy.sh setup     # First time
./scripts/deploy.sh update    # Pull latest + restart
./scripts/deploy.sh status    # Service status
./scripts/deploy.sh logs      # Tail logs
```

## Agent Communication

Agents communicate via **peer reports** (Markdown files in `reports/`). When agent A lists agent B as a "linked agent" in its `.md`, it reads B's recent reports as context.

The project pipeline flows like this:

```
notes/ → portfolio → specifier → planner → architect → presenter
         (requirements) (specs)    (roadmap) (architecture) (deck)
```

Each step produces versioned outputs with `/draft`, `/finalize`, `/rollback`.

## Hierarchical RAG

Agent Hub uses a **two-pass hierarchical search** instead of flat RAG. Each chunk is tagged with a documentation level at ingestion:

| Level | Source | Content |
|---|---|---|
| `L0` | `synthesis/L0_*.md` | Architecture overview (1 file) |
| `L1` | `synthesis/L1_*.md` | Layer overviews (backend, frontend, etc.) |
| `L2` | `synthesis/L2_*.md` | Module documentation |
| `L3` | `codex_*.md` | Per-file scan docs |
| `code` | `workspace/` | Raw source code |
| `context` | `architecture/`, `code-samples/` | Manual context docs |
| `report` | `reports/` | Agent session reports |

When an agent searches for context, the system does:
1. **Pass 1**: Search synthesis docs (L0, L1, L2) for architectural context
2. **Pass 2**: Search detailed docs (L3, code, context) for implementation specifics
3. **Merge**: Deduplicate and sort by relevance score

This means questions about architecture get high-level answers, while questions about specific code get implementation details — without mixing noise from unrelated layers.

The hierarchical search is backward-compatible: on older indexes without `doc_level` metadata, it falls back to flat search automatically. To take full advantage, re-index after upgrading:

```bash
python run.py --clear-index --ingest
```

## Web UI Features

The web UI (`python -m web.server`) includes:

- **Agent selector**: all core agents + custom agents with `web: yes`
- **Conversation history**: per session, per agent
- **Mermaid diagram rendering**: diagrams from agents (class, sequence, ER, flowchart) render as interactive SVGs directly in the chat
- **Stats**: query count, index size, active sessions
- **Query logs**: JSONL per day, accessible via `/api/logs`

## License

MIT
