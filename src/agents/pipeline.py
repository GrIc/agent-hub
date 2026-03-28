"""
Pipeline orchestrator — sequential multi-agent workflow with user validation.

Usage (from CLI):
    /pipeline                    -- Start the full pipeline
    /pipeline from specifier     -- Resume from a specific step
    /pipeline status             -- Show pipeline progress

Each step:
  1. Agent works autonomously, can query other agents via inter-agent messaging
  2. User sees all exchanges and validates output
  3. User can /finalize (proceed), /draft (retry), /rollback, or give feedback

Pipeline steps:
  portfolio -> specifier -> planner -> storyteller -> presenter -> developer
"""

import logging
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.markdown import Markdown

logger = logging.getLogger(__name__)
console = Console()

PIPELINE_STEPS = [
    {
        "agent": "portfolio",
        "label": "Requirements",
        "description": "Transform notes into functional requirements",
        "doc_type": "requirements",
        "needs_input": True,
    },
    {
        "agent": "specifier",
        "label": "Specifications + Architecture",
        "description": "Translate requirements into technical specifications and architecture",
        "doc_type": "specifications",
    },
    {
        "agent": "planner",
        "label": "Roadmap",
        "description": "Break specifications into tasks with timeline",
        "doc_type": "roadmap",
    },
    {
        "agent": "storyteller",
        "label": "Synthesis",
        "description": "Produce a unified techno-functional synthesis document",
        "doc_type": "synthesis",
    },
    {
        "agent": "presenter",
        "label": "Presentation",
        "description": "Create a 10-slide deck from the synthesis",
        "doc_type": "deck",
    },
    {
        "agent": "developer",
        "label": "Implementation",
        "description": "Generate git diffs for each planned task",
        "doc_type": None,  # Developer produces diffs, not versioned project docs
    },
]


class AgentMessenger:
    """
    Handles inter-agent messaging during pipeline execution.

    When an agent needs information, it can query another agent.
    All exchanges are visible to the user and logged.
    If agents can't resolve a question among themselves, the user is asked.
    """

    def __init__(self, agent_factory, cfg, client, store, project):
        self.agent_factory = agent_factory
        self.cfg = cfg
        self.client = client
        self.store = store
        self.project = project
        self.exchange_log: list[dict] = []

    def query_agent(
        self,
        from_agent: str,
        to_agent: str,
        question: str,
    ) -> str:
        """
        Send a question from one agent to another.
        Returns the answer. All exchanges are logged and displayed.
        """
        console.print(
            f"\n[bold yellow]  [{from_agent} → {to_agent}][/bold yellow] {question}"
        )

        self.exchange_log.append({
            "from": from_agent,
            "to": to_agent,
            "question": question,
        })

        try:
            target = self.agent_factory(
                to_agent, self.cfg, self.client, self.store, self.project
            )
            if target is None:
                return f"[Agent {to_agent} unavailable]"

            answer = target.chat(question)
            display = answer[:500] + ("..." if len(answer) > 500 else "")
            console.print(
                f"[bold blue]  [{to_agent} → {from_agent}][/bold blue] {display}"
            )

            self.exchange_log.append({
                "from": to_agent,
                "to": from_agent,
                "answer": answer[:2000],
            })

            return answer

        except Exception as e:
            logger.error(f"Inter-agent query failed ({from_agent} → {to_agent}): {e}")
            return f"[Error querying {to_agent}: {e}]"

    def ask_user(self, from_agent: str, question: str) -> str:
        """
        Escalate a question to the user (after agents couldn't resolve it).
        """
        console.print(
            f"\n[bold magenta]  [{from_agent} → User][/bold magenta] {question}"
        )
        try:
            answer = Prompt.ask(f"[bold cyan]  Your answer[/bold cyan]")
            self.exchange_log.append({
                "from": "user",
                "to": from_agent,
                "answer": answer,
            })
            return answer
        except (KeyboardInterrupt, EOFError):
            return "[User declined to answer]"


def show_pipeline_status(project):
    """Show which pipeline steps have outputs."""
    outputs = project.get_all_latest_outputs() if project else {}
    console.print("\n[bold]Pipeline status:[/bold]")
    for step in PIPELINE_STEPS:
        doc = step.get("doc_type", "")
        if doc and doc in outputs:
            _, version = outputs[doc]
            status = f"[green]✅ v{version}[/green]"
        else:
            status = "[dim]⬜ not started[/dim]"
        console.print(f"  {status}  {step['label']} ({step['agent']})")


def run_pipeline(
    cfg: dict,
    client,
    store,
    project,
    project_name: str,
    agent_factory,
    start_from: str = "",
):
    """
    Execute the pipeline with user validation at each step.

    Args:
        cfg: Configuration dict
        client: ResilientClient
        store: VectorStore
        project: Project instance
        project_name: Project name string
        agent_factory: Function(name, cfg, client, store, project) -> agent
        start_from: Agent name to start from (empty = from beginning)
    """
    messenger = AgentMessenger(agent_factory, cfg, client, store, project)

    # Determine starting step
    start_idx = 0
    if start_from:
        for i, step in enumerate(PIPELINE_STEPS):
            if step["agent"] == start_from:
                start_idx = i
                break
        else:
            console.print(f"[red]Unknown pipeline step: {start_from}[/red]")
            console.print(
                f"[dim]Available: {', '.join(s['agent'] for s in PIPELINE_STEPS)}[/dim]"
            )
            return "abort"

    steps_display = " → ".join(
        f"[bold]{s['label']}[/bold]" if i >= start_idx else f"[dim]{s['label']}[/dim]"
        for i, s in enumerate(PIPELINE_STEPS)
    )

    console.print(Panel(
        f"[bold]Pipeline: {project_name}[/bold]\n"
        f"Steps: {steps_display}\n"
        f"Starting from: {PIPELINE_STEPS[start_idx]['label']}\n"
        f"\nAt each step you can:\n"
        f"  • Chat with the agent to refine the output\n"
        f"  • [bold]/finalize[/bold] — validate and move to next step\n"
        f"  • [bold]/draft[/bold]    — ask for a new draft\n"
        f"  • [bold]/rollback[/bold] N — rollback to version N\n"
        f"  • [bold]/skip[/bold]     — skip this step\n"
        f"  • [bold]/abort[/bold]    — abort the pipeline",
        title="Pipeline Mode",
        border_style="magenta",
    ))

    for step_idx in range(start_idx, len(PIPELINE_STEPS)):
        step = PIPELINE_STEPS[step_idx]
        step_num = step_idx + 1
        total = len(PIPELINE_STEPS)

        console.print(Panel(
            f"[bold]{step['label']}[/bold] — {step['description']}\n"
            f"Agent: {step['agent']}",
            title=f"Step {step_num}/{total}",
            border_style="blue",
        ))

        # Create the agent for this step
        try:
            agent = agent_factory(step["agent"], cfg, client, store, project)
            if agent is None:
                console.print(
                    f"[red]Cannot create agent '{step['agent']}'. Skipping.[/red]"
                )
                continue
        except Exception as e:
            console.print(f"[red]Agent creation error: {e}[/red]")
            continue

        # Auto-load context for project agents
        if hasattr(agent, "_load_project_context"):
            try:
                load_result = agent._load_project_context()
                console.print(f"[dim]{load_result}[/dim]")
            except Exception:
                pass

        # Hint for the first step
        if step.get("needs_input") and step_idx == start_idx:
            console.print(
                "[yellow]Load your notes first with /load, "
                "then start the conversation.[/yellow]"
            )

        # Enter agent conversation loop for this step
        step_result = _step_loop(agent, step, project_name)

        if step_result == "abort":
            console.print("[red]Pipeline aborted.[/red]")
            return "abort"
        elif step_result == "skip":
            console.print(f"[yellow]Skipped: {step['label']}[/yellow]")
            continue
        # "finalized" -> continue to next step

    console.print(Panel(
        f"[bold green]Pipeline complete for {project_name}![/bold green]\n"
        f"All documents have been generated.\n"
        f"Use /versions to review, /rollback to revert any step.",
        border_style="green",
    ))
    return "complete"


def _step_loop(agent, step, project_name) -> str:
    """
    Interactive loop for a single pipeline step.
    Returns: "finalized", "skip", or "abort"
    """
    while True:
        try:
            prompt_prefix = f"(pipeline:{step['agent']}:{project_name})"
            user_input = Prompt.ask(f"\n[bold cyan]{prompt_prefix}[/bold cyan]")
        except (KeyboardInterrupt, EOFError):
            return "abort"

        if not user_input.strip():
            continue

        cmd = user_input.strip().lower()

        if cmd == "/abort":
            return "abort"
        if cmd == "/skip":
            return "skip"
        if cmd == "/finalize":
            # Trigger finalization via the agent
            try:
                with console.status("[bold green]Finalizing...", spinner="dots"):
                    doc_type = step.get("doc_type", "document")
                    response = agent.chat(
                        f"Generate the FINAL {doc_type}. "
                        f"Resolve all [TO BE CLARIFIED] items or list them "
                        f"in Assumptions. Use the appropriate output format tag."
                    )
                console.print(f"\n[bold green]({step['agent']}):[/bold green]")
                try:
                    console.print(Markdown(response))
                except Exception:
                    console.print(response)
            except Exception as e:
                console.print(f"[red]Finalization error: {e}[/red]")
            return "finalized"

        # Regular chat or agent commands
        try:
            # Let the agent handle /commands first
            if user_input.startswith("/"):
                cmd_result = agent.handle_command(user_input)
                if cmd_result is not None:
                    console.print(cmd_result)
                    continue

            with console.status("[bold green]Thinking...", spinner="dots"):
                response = agent.chat(user_input)
            console.print(f"\n[bold green]({step['agent']}):[/bold green]")
            try:
                console.print(Markdown(response))
            except Exception:
                console.print(response)
        except KeyboardInterrupt:
            console.print("\n[yellow]Request cancelled.[/yellow]")
        except Exception as e:
            console.print(f"\n[bold red]Error: {e}[/bold red]")
            logger.exception("Pipeline step error")