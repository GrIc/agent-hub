# Contributing to Agent Hub

Thank you for your interest in contributing to Agent Hub! This document provides
guidelines and information for contributors.

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/GrIc/agent-hub.git`
3. Create a branch: `git checkout -b feature/my-feature`
4. Make your changes
5. Test locally: `python run.py --agent expert --skip-ingest`
6. Commit: `git commit -m "Add my feature"`
7. Push: `git push origin feature/my-feature`
8. Open a Pull Request

## Development Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
pip install -r requirements.txt
cp .env.example .env             # Edit with your API credentials
```

## Project Structure

- `src/` — Python source code (agents, RAG, config)
- `web/` — Web UI (FastAPI server, HTML pages)
- `agents/defs/` — Agent definitions (Markdown)
- `scripts/` — Deployment and Docker helpers

## Adding a New Core Agent

1. Create `agents/defs/youragent.md` with `## Config`, `## Role`, `## Behavior`
2. Create `src/agents/youragent.py` extending `BaseAgent` or `ProjectAgent`
3. Register it in `src/main.py` (imports + `CORE_*_AGENTS` dict)
4. Register it in `src/agent_defs.py` (`CORE_AGENTS` set)
5. If web-enabled, add to `web/server.py` (`CORE_WEB_AGENTS`)

## Adding a Custom Agent (No Python)

Just drop a `.md` file in `agents/defs/`. See `README.md` → Custom Agents.

## Code Style

- Python 3.12+, type hints encouraged
- Docstrings on public functions
- All user-facing text in English
- Follow existing patterns in the codebase

## Reporting Issues

- Use GitHub Issues
- Include: steps to reproduce, expected behavior, actual behavior
- For LLM-related issues, include the model name and provider

## License

By contributing, you agree that your contributions will be licensed under the
Apache License 2.0.