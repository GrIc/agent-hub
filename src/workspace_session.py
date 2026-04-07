"""
Workspace session manager — persistent agent instances for the web UI.

Each session holds a project, a current agent (real Python instance with state),
and conversation history. Sessions are LRU-evicted when the limit is reached.

Max concurrent sessions: configurable (default 5).
"""

import logging
import time
from collections import OrderedDict
from pathlib import Path
from typing import Optional

from src.config import (
    load_config, get_model_for_agent, get_agent_temperature,
    build_custom_dsl_context, build_domain_context, get_agent_extra_params,
)
from src.agents.pipeline import PIPELINE_STEPS
from src.client import ResilientClient
from src.rag.store import VectorStore
from src.projects import Project, get_or_create_project, list_projects
from src.agent_defs import load_agent_definition, list_available_agents
from src.agents.pipeline import PIPELINE_STEPS

# Core agent classes
from src.agents.base import BaseAgent
from src.agents.project_agent import ProjectAgent
from src.agents.codex import CodexAgent
from src.agents.documenter import DocumenterAgent
from src.agents.developer import DeveloperAgent
from src.agents.portfolio import PortfolioAgent
from src.agents.specifier import SpecifierAgent
from src.agents.planner import PlannerAgent
from src.agents.storyteller import StorytellerAgent
from src.agents.presenter import PresenterAgent

logger = logging.getLogger(__name__)

# Agent class registry
AGENT_CLASSES = {
    "codex": CodexAgent,
    "documenter": DocumenterAgent,
    "developer": DeveloperAgent,
    "portfolio": PortfolioAgent,
    "specifier": SpecifierAgent,
    "planner": PlannerAgent,
    "storyteller": StorytellerAgent,
    "presenter": PresenterAgent,
}

# Project-scoped agents
PROJECT_AGENT_NAMES = {
    "portfolio", "specifier", "planner", "storyteller", "presenter",
}

# All agents available in workspace (including CLI-only ones)
ALL_WORKSPACE_AGENTS = {
    "expert":      {"emoji": "🧠", "desc": "Code Q&A, review & debug", "scope": "global"},
    "codex":       {"emoji": "🔬", "desc": "Scan codebase, generate docs for RAG", "scope": "global"},
    "documenter":  {"emoji": "📐", "desc": "Architecture docs & diagrams", "scope": "global"},
    "developer":   {"emoji": "🔧", "desc": "Implement tasks, generate git diffs", "scope": "global"},
    "portfolio":   {"emoji": "📋", "desc": "Notes -> functional requirements", "scope": "project"},
    "specifier":   {"emoji": "📝", "desc": "Requirements -> specs + architecture", "scope": "project"},
    "planner":     {"emoji": "📅", "desc": "Specs -> roadmap with tasks", "scope": "project"},
    "storyteller": {"emoji": "📖", "desc": "All docs -> techno-functional synthesis", "scope": "project"},
    "presenter":   {"emoji": "🎬", "desc": "Synthesis -> slide deck", "scope": "project"},
}


class WorkspaceSession:
    """A single workspace session with a persistent agent."""

    def __init__(self, session_id: str, cfg: dict, client: ResilientClient, store: VectorStore):
        self.session_id = session_id
        self.cfg = cfg
        self.client = client
        self.store = store

        self.project: Optional[Project] = None
        self.project_name: Optional[str] = None
        self.agent: Optional[BaseAgent] = None
        self.agent_name: Optional[str] = None

        # Pipeline state
        self.pipeline_active = False
        self.pipeline_step_idx = 0

        self.created_at = time.time()
        self.last_active = time.time()

    def touch(self):
        self.last_active = time.time()

    def set_project(self, name: str) -> dict:
        """Set or create the active project."""
        self.project = get_or_create_project(name)
        self.project_name = name
        self.agent = None
        self.agent_name = None
        self.pipeline_active = False
        return {"project": name, "status": "ok"}

    def switch_agent(self, agent_name: str) -> dict:
        """Switch to a different agent, creating a new instance."""
        self.touch()

        if agent_name in PROJECT_AGENT_NAMES and not self.project:
            return {"error": f"Agent '{agent_name}' requires a project. Set a project first."}

        try:
            self.agent = self._create_agent(agent_name)
            self.agent_name = agent_name
            self.pipeline_active = False
            return {
                "agent": agent_name,
                "info": ALL_WORKSPACE_AGENTS.get(agent_name, {}),
                "status": "ok",
            }
        except Exception as e:
            logger.error(f"[Session {self.session_id}] Agent creation failed: {e}")
            return {"error": str(e)}

    def chat(self, message: str) -> dict:
        """Send a message or /command to the active agent."""
        self.touch()

        if not self.agent:
            return {"error": "No agent active. Switch to an agent first."}

        try:
            # Handle /commands that return a string
            if message.startswith("/"):
                cmd_result = self.agent.handle_command(message)
                if cmd_result is not None:
                    return self._build_response(cmd_result, is_command=True)

            # Regular chat
            response = self.agent.chat(message)
            return self._build_response(response)

        except Exception as e:
            logger.exception(f"[Session {self.session_id}] Chat error")
            return {"error": f"{type(e).__name__}: {str(e)[:300]}"}

    def _build_response(self, response: str, is_command: bool = False) -> dict:
        """Build a response dict with metadata about generated files."""
        result = {
            "answer": response,
            "agent": self.agent_name,
            "is_command": is_command,
        }

        # Include info about files generated in this response
        if self.agent and hasattr(self.agent, "files_generated") and self.agent.files_generated:
            result["files_generated"] = list(self.agent.files_generated)

        # Include pipeline state
        if self.pipeline_active:
            step = None
            if self.pipeline_step_idx < len(PIPELINE_STEPS):
                step = PIPELINE_STEPS[self.pipeline_step_idx]
            result["pipeline"] = {
                "active": True,
                "step_idx": self.pipeline_step_idx,
                "step": step,
                "total_steps": len(PIPELINE_STEPS),
            }

        # Check for recently saved versioned outputs (for right panel auto-update)
        if self.project and self.agent and hasattr(self.agent, "doc_type"):
            doc_type = getattr(self.agent, "doc_type", None)
            if doc_type:
                latest = self.project.load_latest_output(doc_type)
                if latest:
                    content, version = latest
                    result["latest_output"] = {
                        "doc_type": doc_type,
                        "version": version,
                        "path": f"outputs/{doc_type}_v{version}.md",
                    }

        return result

    def start_pipeline(self, start_from: str = "") -> dict:
        """Start the pipeline from a given step."""
        if not self.project:
            return {"error": "Pipeline requires a project. Set a project first."}

        start_idx = 0
        if start_from:
            for i, step in enumerate(PIPELINE_STEPS):
                if step["agent"] == start_from:
                    start_idx = i
                    break
            else:
                return {"error": f"Unknown pipeline step: {start_from}"}

        self.pipeline_active = True
        self.pipeline_step_idx = start_idx

        # Switch to the first agent
        step = PIPELINE_STEPS[start_idx]
        self.switch_agent(step["agent"])

        # Auto-load project context
        if self.agent and hasattr(self.agent, "_load_project_context"):
            try:
                getattr(self.agent, "_load_project_context")()
            except Exception:
                pass

        return {
            "status": "started",
            "step_idx": start_idx,
            "step": step,
            "total_steps": len(PIPELINE_STEPS),
            "agent": step["agent"],
        }

    def pipeline_next(self) -> dict:
        """Advance to the next pipeline step."""
        if not self.pipeline_active:
            return {"error": "No active pipeline."}

        self.pipeline_step_idx += 1
        if self.pipeline_step_idx >= len(PIPELINE_STEPS):
            self.pipeline_active = False
            return {"status": "complete", "message": "Pipeline complete!"}

        step = PIPELINE_STEPS[self.pipeline_step_idx]
        self.switch_agent(step["agent"])

        # Auto-load context
        if self.agent and hasattr(self.agent, "_load_project_context"):
            try:
                getattr(self.agent, "_load_project_context")()
            except Exception:
                pass

        return {
            "status": "next",
            "step_idx": self.pipeline_step_idx,
            "step": step,
            "total_steps": len(PIPELINE_STEPS),
            "agent": step["agent"],
        }

    def pipeline_skip(self) -> dict:
        """Skip the current pipeline step."""
        return self.pipeline_next()

    def pipeline_abort(self) -> dict:
        """Abort the pipeline."""
        self.pipeline_active = False
        return {"status": "aborted"}

    def _create_agent(self, name: str) -> BaseAgent:
        """Create a real agent instance with full context."""
        model = get_model_for_agent(self.cfg, name)
        temperature = get_agent_temperature(self.cfg, name)
        dsl_context = build_custom_dsl_context(self.cfg)
        domain_context = build_domain_context(self.cfg)
        extra_params = get_agent_extra_params(self.cfg, name)

        kwargs = {
            "client": self.client,
            "store": self.store,
            "model": model,
            "temperature": temperature,
            "rag_top_k": self.cfg.get("rag", {}).get("rerank_top_k", 4),
            "custom_dsl_info": dsl_context,
            "domain_info": domain_context,
            "extra_params": extra_params,
        }

        agent_class = AGENT_CLASSES.get(name)

        if agent_class:
            # Core agent with dedicated Python class
            if name in PROJECT_AGENT_NAMES and self.project:
                kwargs["project"] = self.project
            if name in ("developer", "codex"):
                kwargs["workspace_path"] = self.cfg.get("_defaults", {}).get(
                    "workspace_path", "./workspace"
                )
            if name == "developer":
                kwargs["scm_config"] = self.cfg.get("scm", {})
            return agent_class(**kwargs)

        elif name == "expert":
            # Expert is BaseAgent with custom prompt
            agent = BaseAgent(**kwargs)
            agent.name = "expert"
            definition = load_agent_definition("expert")
            agent._system_prompt = definition["system_prompt"]
            agent._peers = definition["peers"]
            return agent

        else:
            # Custom agent from .md definition
            definition = load_agent_definition(name)
            md_config = definition.get("config", {})
            scope = md_config.get("scope", "global")

            if scope == "project" and self.project:
                kwargs["project"] = self.project
                agent = ProjectAgent(**kwargs)
                agent.doc_type = md_config.get("doc_type", name)
                agent.output_tag = md_config.get("output_tag", f"{name}_md")
                agent.upstream_types = md_config.get("upstream_types", [])
            else:
                agent = BaseAgent(**kwargs)

            agent.name = name
            agent._system_prompt = definition["system_prompt"]
            agent._peers = definition["peers"]
            return agent

    def get_state(self) -> dict:
        """Return current session state for the frontend."""
        state = {
            "session_id": self.session_id,
            "project": self.project_name,
            "agent": self.agent_name,
            "agent_info": ALL_WORKSPACE_AGENTS.get(self.agent_name or "", {}),
            "history_length": len(self.agent.history) if self.agent else 0,
        }
        if self.pipeline_active:
            step = PIPELINE_STEPS[self.pipeline_step_idx] if self.pipeline_step_idx < len(PIPELINE_STEPS) else None
            state["pipeline"] = {
                "active": True,
                "step_idx": self.pipeline_step_idx,
                "step": step,
                "total_steps": len(PIPELINE_STEPS),
            }
        return state


class SessionManager:
    """
    Manages workspace sessions with LRU eviction.

    Thread-safety: FastAPI runs in a single event loop, so no locks needed
    for the dict operations. Agent chat() calls are synchronous and blocking
    (they call the LLM API), which is fine for the workspace use case.
    """

    def __init__(self, cfg: dict, client: ResilientClient, store: VectorStore,
                 max_sessions: int = 5):
        self.cfg = cfg
        self.client = client
        self.store = store
        self.max_sessions = max_sessions
        self.sessions: OrderedDict[str, WorkspaceSession] = OrderedDict()

    def get_or_create(self, session_id: str) -> WorkspaceSession:
        """Get an existing session or create a new one."""
        if session_id in self.sessions:
            self.sessions.move_to_end(session_id)
            session = self.sessions[session_id]
            session.touch()
            return session

        # Evict oldest if at capacity
        while len(self.sessions) >= self.max_sessions:
            evicted_id, evicted = self.sessions.popitem(last=False)
            logger.info(
                f"[SessionManager] Evicted session {evicted_id} "
                f"(idle {time.time() - evicted.last_active:.0f}s)"
            )

        session = WorkspaceSession(session_id, self.cfg, self.client, self.store)
        self.sessions[session_id] = session
        logger.info(
            f"[SessionManager] Created session {session_id} "
            f"({len(self.sessions)}/{self.max_sessions})"
        )
        return session

    def get(self, session_id: str) -> Optional[WorkspaceSession]:
        """Get a session without creating."""
        if session_id in self.sessions:
            self.sessions.move_to_end(session_id)
            return self.sessions[session_id]
        return None

    def destroy(self, session_id: str) -> bool:
        """Destroy a session."""
        if session_id in self.sessions:
            del self.sessions[session_id]
            return True
        return False

    @property
    def count(self) -> int:
        return len(self.sessions)