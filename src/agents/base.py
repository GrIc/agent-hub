"""
Base agent class. All specialized agents inherit from this.
Provides: markdown-based prompt, RAG retrieval (hierarchical), peer reports, CR generation.
"""

import logging
import re
from typing import Optional

from src.client import ResilientClient
from src.rag.store import VectorStore
from src.agent_defs import load_agent_definition
from src.reports import save_report, load_peer_reports, list_reports

logger = logging.getLogger(__name__)


class BaseAgent:
    """
    Base conversational agent with:
    - System prompt loaded from agents/defs/{name}.md
    - Hierarchical RAG context injection (synthesis first, then details)
    - Peer reports injection (recent CRs from linked agents)
    - Global domain context injection (from config.yaml → domain section)
    - Per-agent functional context injection (from ## Functional context in .md)
    - Optional extra API params per agent (e.g. reasoning_effort)
    - Automatic CR generation on /save or session end

    Subclasses override:
        - name: str
        - handle_command(cmd): for special /commands
        - post_process(response): to generate files, etc.
    """

    name: str = "base"

    def __init__(
        self,
        client: ResilientClient,
        store: VectorStore,
        model: str,
        temperature: float = 0.5,
        rag_top_k: int = 8,
        custom_dsl_info: str = "",
        domain_info: str = "",
        extra_params: Optional[dict] = None,
    ):
        self.client = client
        self.store = store
        self.model = model
        self.temperature = temperature
        self.rag_top_k = rag_top_k
        self.custom_dsl_info = custom_dsl_info
        self.domain_info = domain_info
        self.extra_params = extra_params or {}
        self.history: list[dict] = []
        self.actions_log: list[str] = []
        self.files_generated: list[str] = []

        # Load definition from markdown
        definition = load_agent_definition(self.name)
        self._system_prompt = definition["system_prompt"]
        self._peers = definition["peers"]
        self._functional_context = definition.get("functional_context", "")

    def get_system_prompt(self) -> str:
        """Build the full system prompt with optional DSL, domain, and functional context.

        Injection order (each block appended only when non-empty):
          1. Base system prompt (from agents/defs/{name}.md)
          2. Custom DSL context    (config.yaml → custom_dsl)
          3. Global domain context (config.yaml → domain)
          4. Per-agent functional context (## Functional context in .md)
        """
        prompt = self._system_prompt
        if self.custom_dsl_info:
            prompt += f"\n\n## Custom domain language\n{self.custom_dsl_info}"
        if self.domain_info:
            prompt += f"\n\n## Domain context\n{self.domain_info}"
        if self._functional_context:
            prompt += f"\n\n## Agent functional context\n{self._functional_context}"
        return prompt

    def retrieve_context(self, query: str) -> str:
        """
        Hybrid retrieval: vector search + knowledge graph traversal.

        Uses search_hybrid() which combines:
          1. Hierarchical vector search (synthesis + detail docs)
          2. Graph traversal for structural context (if graph is available)

        Falls back to search_hierarchical() if no graph is attached.
        """
        results = self.store.search_hybrid(query, top_k=self.rag_top_k)
        if not results:
            return ""

        context_parts = []
        graph_context = None

        for i, r in enumerate(results, 1):
            source = r["source"]
            score = r["score"]
            text = r["text"]
            level = r.get("doc_level", "")
            level_tag = f" [{level}]" if level else ""
            boosted = " +graph" if r.get("graph_boosted") else ""
            context_parts.append(
                f"--- [Source {i}: {source}{level_tag} (score: {score:.2f}{boosted})] ---\n{text}"
            )
            if r.get("graph_context"):
                graph_context = r["graph_context"]

        context = "\n\n".join(context_parts)

        if graph_context:
            context += (
                "\n\n--- [Structural Context (Knowledge Graph)] ---\n"
                + graph_context
            )

        return context

    def get_peer_reports(self) -> str:
        """Load recent CRs from linked agents."""
        if not self._peers:
            return ""
        return load_peer_reports(self._peers)

    def build_messages(self, user_message: str) -> list[dict]:
        """Construct the full message list: system + peer reports + RAG + history."""
        context = self.retrieve_context(user_message)
        peer_context = self.get_peer_reports()

        system = self.get_system_prompt()

        if peer_context:
            system += f"\n\n{peer_context}"

        if context:
            system += (
                "\n\n## Retrieved context (internal documents)\n"
                "Use this information to answer. Cite sources if relevant.\n\n"
                f"{context}"
            )

        messages = [{"role": "system", "content": system}]
        recent_history = self.history[-20:]
        messages.extend(recent_history)
        messages.append({"role": "user", "content": user_message})

        return messages

    def chat(self, user_message: str) -> str:
        """Main entry point: send a message, get a response."""
        if user_message.startswith("/"):
            cmd_result = self.handle_command(user_message)
            if cmd_result is not None:
                return cmd_result

        messages = self.build_messages(user_message)

        total_chars = sum(len(m["content"]) for m in messages)
        estimated_tokens = total_chars // 3
        logger.debug(f"Estimated input tokens: ~{estimated_tokens}")

        if self.extra_params:
            logger.debug(f"[{self.name}] extra_params: {self.extra_params}")

        response = self.client.chat(
            messages=messages,
            model=self.model,
            temperature=self.temperature,
            max_tokens=4096,
            **self.extra_params,
        )

        self.history.append({"role": "user", "content": user_message})
        self.history.append({"role": "assistant", "content": response})

        final = self.post_process(response)
        return final

    def handle_command(self, cmd: str) -> Optional[str]:
        """Handle /commands. Override in subclasses for agent-specific commands."""
        parts = cmd.strip().split(maxsplit=1)
        command = parts[0].lower()

        if command == "/clear":
            self.history.clear()
            self.actions_log.clear()
            self.files_generated.clear()
            return "Conversation history cleared."

        if command == "/history":
            if not self.history:
                return "No history."
            lines = []
            for msg in self.history[-10:]:
                role = "User" if msg["role"] == "user" else "Agent"
                text = msg["content"][:100] + ("..." if len(msg["content"]) > 100 else "")
                lines.append(f"{role}: {text}")
            return "\n".join(lines)

        if command == "/save":
            return self._generate_report()

        if command == "/reports":
            agent_filter = parts[1].strip() if len(parts) > 1 else None
            return self._list_reports(agent_filter)

        if command == "/undo":
            agent_filter = parts[1].strip() if len(parts) > 1 else self.name
            return self._undo_last_report(agent_filter)

        if command == "/help":
            return self._help_text()

        return None

    def post_process(self, response: str) -> str:
        """Hook for subclasses to process the LLM response. Returns final string."""
        return response

    def _generate_report(self) -> str:
        if not self.history:
            return "No exchanges to summarize."

        summary_prompt = (
            "Summarize this work session in 3 to 8 sentences. "
            "Mention: the topic covered, decisions made, deliverables produced, "
            "and next steps if any. Be factual and concise."
        )

        path = save_report(
            agent_name=self.name,
            history=self.history,
            client=self.client,
            model=self.model,
            summary_prompt=summary_prompt,
        )
        return f"Report saved: {path}"

    def _list_reports(self, agent_filter: Optional[str] = None) -> str:
        reports = list_reports(agent_filter or self.name)
        if not reports:
            return "No reports found."
        lines = [f"  {r['filename']} ({r['date']})" for r in reports[:10]]
        return "Reports:\n" + "\n".join(lines)

    def _undo_last_report(self, agent_name: str) -> str:
        from src.reports import delete_last_report
        deleted = delete_last_report(agent_name)
        if deleted:
            return f"Deleted: {deleted}"
        return f"No report found for '{agent_name}'."

    def _help_text(self) -> str:
        return (
            "Available commands:\n"
            "  /save       — Summarize and save this session as a report\n"
            "  /reports    — List saved reports\n"
            "  /undo       — Delete the last report\n"
            "  /history    — Show recent conversation history\n"
            "  /clear      — Clear conversation history\n"
            "  /help       — Show this help\n"
            "  /quit       — Exit the session"
        )
    
    def log_action(self, action: str):
        self.actions_log.append(action)

    def log_file(self, filepath: str):
        self.files_generated.append(filepath)
