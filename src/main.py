#!/usr/bin/env python3
"""
Agent Hub -- Multi-agent CLI with RAG.

Usage:
    python -m src.main                                      # Interactive menu
    python -m src.main --agent specifier --project my-proj  # Project-scoped agent
    python -m src.main --agent expert                       # Global agent (no project)
    python -m src.main --ingest                             # Index documents only
"""

import argparse
import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.logging import RichHandler
from rich.markdown import Markdown

from src.config import load_config, get_model_for_agent, get_agent_temperature, build_custom_dsl_context, build_domain_context, get_agent_extra_params
from src.client import ResilientClient
from src.rag.ingest import ingest_directory
from src.rag.store import VectorStore
from src.agent_defs import load_agent_definition, list_available_agents, discover_custom_agents
from src.projects import list_projects, get_or_create_project, Project

# Core agents (with dedicated Python classes for special commands)
from src.agents.codex import CodexAgent
from src.agents.documenter import DocumenterAgent
from src.agents.developer import DeveloperAgent
from src.agents.portfolio import PortfolioAgent
from src.agents.specifier import SpecifierAgent
from src.agents.planner import PlannerAgent
from src.agents.presenter import PresenterAgent
from src.agents.storyteller import StorytellerAgent

# Base classes for custom agents
from src.agents.base import BaseAgent
from src.pipeline import run_pipeline, show_pipeline_status, PIPELINE_STEPS
from src.agents.project_agent import ProjectAgent

console = Console()

# ── Core agents (hardcoded, have special /commands) ──────────────

CORE_GLOBAL_AGENTS = {
    "expert":     {"class": None,             "emoji": "🧠", "desc": "Code Q&A (web only)"},
    "codex":      {"class": CodexAgent,       "emoji": "🔬", "desc": "Scan codebase, generate documentation for RAG"},
    "documenter": {"class": DocumenterAgent,  "emoji": "📐", "desc": "Architecture docs & diagrams of existing code"},
    "developer":  {"class": DeveloperAgent,   "emoji": "🔧", "desc": "Implement tasks, modify code in workspace"},
}

CORE_PROJECT_AGENTS = {
    "portfolio":  {"class": PortfolioAgent,   "emoji": "📋", "desc": "Aggregate notes -> requirements"},
    "specifier":  {"class": SpecifierAgent,   "emoji": "📝", "desc": "Requirements -> technical specifications"},
    "planner":    {"class": PlannerAgent,     "emoji": "📅", "desc": "Specifications -> roadmap with tasks"},
    "presenter":  {"class": PresenterAgent,   "emoji": "🎬", "desc": "All docs -> slide deck"},
    "storyteller": {"class": StorytellerAgent, "emoji": "📖", "desc": "All docs -> techno-functional synthesis"},
}


def _build_agent_registry() -> tuple[dict, dict, dict]:
    """
    Build the full agent registry: core + custom agents discovered from .md files.
    Returns (global_agents, project_agents, all_agents).
    """
    global_agents = dict(CORE_GLOBAL_AGENTS)
    project_agents = dict(CORE_PROJECT_AGENTS)

    # Discover custom agents from agents/defs/*.md
    custom = discover_custom_agents()
    for name, definition in custom.items():
        cfg = definition.get("config", {})
        scope = cfg.get("scope", "global")
        emoji = cfg.get("emoji", "🤖")
        desc = cfg.get("description", f"Custom agent: {name}")

        if scope == "project":
            project_agents[name] = {
                "class": "dynamic_project",
                "emoji": emoji,
                "desc": desc,
                "config": cfg,
            }
        else:
            global_agents[name] = {
                "class": "dynamic_global",
                "emoji": emoji,
                "desc": desc,
                "config": cfg,
            }

    all_agents = {**global_agents, **project_agents}
    return global_agents, project_agents, all_agents


# Build registries at import time (rebuilt on each run)
GLOBAL_AGENTS, PROJECT_AGENTS, ALL_AGENTS = _build_agent_registry()


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level, format="%(message)s",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
    )
    for lib in ("httpx", "openai", "chromadb"):
        logging.getLogger(lib).setLevel(logging.WARNING)


def run_ingestion(cfg: dict, client: ResilientClient, store: VectorStore) -> int:
    console.print("\n[bold blue]Indexing documents...[/bold blue]")
    rag_cfg = cfg.get("rag", {})
    extensions = rag_cfg.get("extensions")
    chunk_size = rag_cfg.get("chunk_size", 1000)
    chunk_overlap = rag_cfg.get("chunk_overlap", 150)
    max_chunks = rag_cfg.get("max_chunks", 2000)

    chunks = []
    for label, path in [
        ("context", Path("context")),
        ("workspace", Path(cfg.get("_defaults", {}).get("workspace_path", "./workspace"))),
        ("reports", Path("reports")),
    ]:
        if path.exists():
            ext = [".md"] if label == "reports" else extensions
            chunks.extend(ingest_directory(path, extensions=ext, chunk_size=chunk_size, chunk_overlap=chunk_overlap, label=label))

    if not chunks:
        console.print("[yellow]No documents found.[/yellow]")
        return 0

    if len(chunks) > max_chunks:
        console.print(f"[yellow]{len(chunks)} chunks found, limited to {max_chunks}.[/yellow]")
        chunks = chunks[:max_chunks]

    console.print(f"  {len(chunks)} chunks to index...")
    added = store.add_chunks(chunks)
    console.print(f"  [green]{added} new chunks indexed (total: {store.count})[/green]")
    return added


def show_agent_menu(project_name: str = None):
    table = Table(title="Available agents", show_header=True)
    table.add_column("#", style="bold cyan", width=3)
    table.add_column("Agent", style="bold")
    table.add_column("Description")
    table.add_column("Scope", style="dim")

    i = 1
    for key, info in GLOBAL_AGENTS.items():
        if key == "expert":
            continue
        tag = " [dim](custom)[/dim]" if info.get("class") in ("dynamic_global",) else ""
        table.add_row(str(i), f"{info['emoji']} {key}{tag}", info["desc"], "global")
        i += 1
    for key, info in PROJECT_AGENTS.items():
        scope = f"project: {project_name}" if project_name else "[red]needs --project[/red]"
        tag = " [dim](custom)[/dim]" if info.get("class") in ("dynamic_project",) else ""
        table.add_row(str(i), f"{info['emoji']} {key}{tag}", info["desc"], scope)
        i += 1

    console.print(table)

    projects = list_projects()
    if projects:
        console.print(f"\n[dim]Projects: {', '.join(projects)}[/dim]")
    if project_name:
        console.print(f"[dim]Active project: {project_name}[/dim]")
    else:
        console.print(f"[dim]No project selected. Use --project <n> for project agents.[/dim]")

    console.print(
        "\n[dim]Global commands: /switch, /reindex, /pipeline, /quit[/dim]"
        "\n[dim]Report commands: /save, /reports, /undo[/dim]"
    )


def _create_dynamic_agent(name: str, agent_info: dict, cfg: dict, client: ResilientClient, store: VectorStore, project: Project = None):
    """Create a custom agent dynamically from its .md config."""
    md_config = agent_info.get("config", {})
    scope = md_config.get("scope", "global")

    model_alias = md_config.get("model")
    if model_alias:
        model = cfg["models"].get(model_alias, model_alias)
    else:
        model = get_model_for_agent(cfg, name)

    temperature = md_config.get("temperature")
    if temperature is None:
        temperature = get_agent_temperature(cfg, name)

    dsl_context = build_custom_dsl_context(cfg)
    domain_context = build_domain_context(cfg)

    kwargs = {
        "client": client,
        "store": store,
        "model": model,
        "temperature": temperature,
        "rag_top_k": cfg.get("rag", {}).get("rerank_top_k", 4),
        "custom_dsl_info": dsl_context,
        "domain_info": domain_context,
        "extra_params": md_config.get("extra_params", {}),
    }

    if scope == "project":
        if not project:
            console.print(f"[red]Agent '{name}' requires a project. Use --project <n>.[/red]")
            return None
        kwargs["project"] = project
        agent = ProjectAgent(**kwargs)
        agent.name = name
        agent.doc_type = md_config.get("doc_type", name)
        agent.output_tag = md_config.get("output_tag", f"{name}_md")
        agent.upstream_types = md_config.get("upstream_types", [])
    else:
        agent = BaseAgent(**kwargs)
        agent.name = name

    from src.agent_defs import load_agent_definition
    definition = load_agent_definition(name)
    agent._system_prompt = definition["system_prompt"]
    agent._peers = definition["peers"]

    return agent


def create_agent(name: str, cfg: dict, client: ResilientClient, store: VectorStore, project: Project = None):
    if name not in ALL_AGENTS:
        console.print(f"[red]Unknown agent: {name}[/red]")
        return None

    agent_info = ALL_AGENTS[name]
    agent_class = agent_info["class"]

    if agent_class in ("dynamic_global", "dynamic_project"):
        return _create_dynamic_agent(name, agent_info, cfg, client, store, project)

    if agent_class is None:
        console.print(f"[red]Agent '{name}' is web-only.[/red]")
        return None

    if name in PROJECT_AGENTS and not project:
        console.print(f"[red]Agent '{name}' requires a project. Use --project <n>.[/red]")
        return None

    model = get_model_for_agent(cfg, name)
    temperature = get_agent_temperature(cfg, name)
    dsl_context = build_custom_dsl_context(cfg)
    domain_context = build_domain_context(cfg)
    extra_params = get_agent_extra_params(cfg, name)

    kwargs = {
        "client": client,
        "store": store,
        "model": model,
        "temperature": temperature,
        "rag_top_k": cfg.get("rag", {}).get("rerank_top_k", 4),
        "custom_dsl_info": dsl_context,
        "domain_info": domain_context,
        "extra_params": extra_params,
    }

    if name in PROJECT_AGENTS and project:
        kwargs["project"] = project
    if name in ("developer", "codex"):
        kwargs["workspace_path"] = cfg.get("_defaults", {}).get("workspace_path", "./workspace")
    if name == "developer":
        kwargs["scm_config"] = cfg.get("scm", {})

    return agent_class(**kwargs)


def chat_loop(agent, cfg, client, store, project_name=None):
    agent_info = ALL_AGENTS.get(agent.name, {})
    emoji = agent_info.get("emoji", "🤖")
    peers = agent._peers if hasattr(agent, "_peers") else []
    peers_str = ", ".join(peers) if peers else "none"

    title_parts = [f"[bold]{emoji} Agent: {agent.name}[/bold]"]

    # --- Model + config display (including extra_params) ---
    model_line = f"Model: {agent.model}  |  Temperature: {agent.temperature}"
    title_parts.append(model_line)

    extra_params = getattr(agent, "extra_params", {})
    if extra_params:
        params_str = "  |  ".join(f"{k}: {v}" for k, v in extra_params.items())
        title_parts.append(f"[yellow]Extra params: {params_str}[/yellow]")
    else:
        title_parts.append("[dim]Extra params: (none)[/dim]")

    if project_name:
        title_parts.append(f"Project: {project_name}")
    title_parts.append(f"Linked agents: {peers_str}")
    title_parts.append("Type /help for commands")

    console.print(Panel("\n".join(title_parts), title="Active session", border_style="green"))

    while True:
        try:
            prompt_prefix = f"({agent.name}"
            if project_name:
                prompt_prefix += f":{project_name}"
            prompt_prefix += ")"
            user_input = Prompt.ask(f"\n[bold cyan]{prompt_prefix}[/bold cyan]")
        except (KeyboardInterrupt, EOFError):
            if agent.history:
                try:
                    save = Prompt.ask("[yellow]Save a report?[/yellow]", choices=["y", "n"], default="y")
                    if save == "y":
                        console.print(agent.handle_command("/save"))
                except (KeyboardInterrupt, EOFError):
                    pass
            return "quit"

        if not user_input.strip():
            continue

        cmd = user_input.strip().lower()
        if cmd in ("/quit", "/exit", "/q"):
            if agent.history:
                try:
                    save = Prompt.ask("[yellow]Save a report?[/yellow]", choices=["y", "n"], default="y")
                    if save == "y":
                        console.print(agent.handle_command("/save"))
                except (KeyboardInterrupt, EOFError):
                    pass
            return "quit"
        if cmd == "/switch":
            if agent.history:
                try:
                    save = Prompt.ask("[yellow]Save a report before switching?[/yellow]", choices=["y", "n"], default="y")
                    if save == "y":
                        console.print(agent.handle_command("/save"))
                except (KeyboardInterrupt, EOFError):
                    pass
            return "switch"
        if cmd == "/reindex":
            run_ingestion(cfg, client, store)
            continue
        if cmd.startswith("/pipeline"):
            if not project_name:
                console.print("[red]Pipeline requires a project. Use --project <n>.[/red]")
                continue
            parts = cmd.split()
            project = get_or_create_project(project_name)
            if len(parts) > 1 and parts[1] == "status":
                show_pipeline_status(project)
                continue
            start_from = ""
            if len(parts) > 2 and parts[1] == "from":
                start_from = parts[2]
            run_pipeline(
                cfg, client, store, project, project_name,
                agent_factory=create_agent,
                start_from=start_from,
            )
            continue

        try:
            with console.status("[bold green]Thinking...", spinner="dots"):
                response = agent.chat(user_input)
            console.print(f"\n[bold green]({agent.name}):[/bold green]")
            try:
                console.print(Markdown(response))
            except Exception:
                console.print(response)
        except KeyboardInterrupt:
            console.print("\n[yellow]Request cancelled.[/yellow]")
        except Exception as e:
            console.print(f"\n[bold red]Error: {e}[/bold red]")
            logging.getLogger(__name__).exception("Agent error")


def main():
    parser = argparse.ArgumentParser(description="Agent Hub -- Multi-agent CLI with RAG")
    all_names = [k for k in ALL_AGENTS if k != "expert"]
    parser.add_argument("--agent", "-a", choices=all_names, help="Start with a specific agent")
    parser.add_argument("--project", "-p", type=str, help="Project name (required for project agents)")
    parser.add_argument("--ingest", "-i", action="store_true", help="Index documents and quit")
    parser.add_argument("--skip-ingest", "-s", action="store_true", help="Skip indexing at startup")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logs")
    parser.add_argument("--config", "-c", default="config.yaml", help="Configuration file")
    parser.add_argument("--clear-index", action="store_true", help="Delete index and re-index")
    parser.add_argument("--clean", action="store_true", help="Clean: delete index, outputs")
    args = parser.parse_args()

    setup_logging(args.verbose)

    if args.clean:
        import shutil
        for d in [".vectordb", "output"]:
            p = Path(d)
            if p.exists():
                shutil.rmtree(p)
                console.print(f"[yellow]Deleted: {d}/[/yellow]")
        console.print("[green]Cleanup done.[/green]")
        sys.exit(0)

    cfg = load_config(args.config)
    defaults = cfg.get("_defaults", {})

    if not defaults.get("api_base_url") or not defaults.get("api_key"):
        console.print("[bold red]API_BASE_URL and API_KEY must be set in .env[/bold red]")
        sys.exit(1)

    project = None
    project_name = args.project
    if project_name:
        project = get_or_create_project(project_name)
        console.print(f"[dim]Project: {project_name}[/dim]")

    console.print(Panel(
        "[bold]Agent Hub[/bold]\n"
        "Multi-agent system with RAG\n"
        f"Agents: {len(ALL_AGENTS)} ({len(GLOBAL_AGENTS)} global, {len(PROJECT_AGENTS)} project)",
        border_style="blue",
    ))

    try:
        client = ResilientClient(
            api_key=defaults["api_key"],
            base_url=defaults["api_base_url"],
            max_retries=defaults.get("retry_max_attempts", 8),
            base_delay=defaults.get("retry_base_delay", 2.0),
            max_delay=defaults.get("retry_max_delay", 120.0),
        )
    except Exception as e:
        console.print(f"[bold red]API client error: {e}[/bold red]")
        sys.exit(1)

    try:
        embed_model = cfg["models"].get("embed", "")
        rerank_model = cfg["models"].get("rerank", "")
        store = VectorStore(client=client, embed_model=embed_model, rerank_model=rerank_model)
        logging.getLogger(__name__).info(f"VectorStore ready: {store.count} chunks")
    except Exception as e:
        console.print(f"[bold red]VectorStore error: {type(e).__name__}: {e}[/bold red]")
        console.print("[dim]Try: python run.py --clean[/dim]")
        sys.exit(1)

    if args.clear_index:
        store.clear()
        console.print("[yellow]Index cleared.[/yellow]")

    if not args.skip_ingest:
        try:
            run_ingestion(cfg, client, store)
        except Exception as e:
            console.print(f"[bold red]Indexing error: {e}[/bold red]")
            logging.getLogger(__name__).exception("Ingestion failed")
    else:
        console.print(f"[dim]Indexing skipped. Existing index: {store.count} chunks.[/dim]")

    if args.ingest:
        console.print("[green]Indexing complete.[/green]")
        sys.exit(0)

    while True:
        if args.agent:
            agent_name = args.agent
            args.agent = None
        else:
            show_agent_menu(project_name)
            try:
                choice = Prompt.ask("\n[bold]Choose an agent[/bold] (number or name)", default="developer")
            except (KeyboardInterrupt, EOFError):
                console.print("\n[dim]Goodbye![/dim]")
                break

            selectable = [k for k in list(GLOBAL_AGENTS.keys()) + list(PROJECT_AGENTS.keys()) if k != "expert"]
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(selectable):
                    agent_name = selectable[idx]
                else:
                    console.print("[red]Invalid number.[/red]")
                    continue
            elif choice in ALL_AGENTS and choice != "expert":
                agent_name = choice
            else:
                console.print(f"[red]Unknown agent: {choice}[/red]")
                continue

        if agent_name in PROJECT_AGENTS and not project_name:
            try:
                project_name = Prompt.ask("[bold]This agent requires a project. Enter project name[/bold]")
                project = get_or_create_project(project_name)
            except (KeyboardInterrupt, EOFError):
                continue

        try:
            agent = create_agent(agent_name, cfg, client, store, project)
            if agent is None:
                continue
        except Exception as e:
            console.print(f"[bold red]Agent creation error '{agent_name}':[/bold red]")
            import traceback
            traceback.print_exc()
            continue

        try:
            result = chat_loop(agent, cfg, client, store, project_name)
        except Exception as e:
            console.print(f"[bold red]Chat loop error:[/bold red]")
            import traceback
            traceback.print_exc()
            result = "switch"

        if result == "quit":
            console.print("\n[dim]Goodbye![/dim]")
            break


if __name__ == "__main__":
    main()
