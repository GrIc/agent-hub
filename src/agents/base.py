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
from src.reports import save_report, load_peer_reports, list_reports, delete_last_report

logger = logging.getLogger(__name__)


class BaseAgent:
    """
    Base conversational agent with:
    - System prompt loaded from agents/defs/{name}.md
    - Hierarchical RAG context injection (synthesis first, then details)
    - Peer reports injection (recent CRs from linked agents)
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
    ):
        self.client = client
        self.store = store
        self.model = model
        self.temperature = temperature
        self.rag_top_k = rag_top_k
        self.custom_dsl_info = custom_dsl_info
        self.history: list[dict] = []
        self.actions_log: list[str] = []
        self.files_generated: list[str] = []

        # Load definition from markdown
        definition = load_agent_definition(self.name)
        self._system_prompt = definition["system_prompt"]
        self._peers = definition["peers"]

    def get_system_prompt(self) -> str:
        """Build the full system prompt with optional DSL context."""
        prompt = self._system_prompt
        if self.custom_dsl_info:
            prompt += f"\n\n## Custom domain language\n{self.custom_dsl_info}"
        return prompt

    def retrieve_context(self, query: str) -> str:
        """
        Search the vector store using hierarchical two-pass retrieval:
          1. Synthesis docs (L0, L1, L2) for architectural context
          2. Detailed docs (L3, code) for implementation specifics

        Falls back to flat search on older indexes without doc_level metadata.
        """
        results = self.store.search_hierarchical(query, top_k=self.rag_top_k)
        if not results:
            return ""

        context_parts = []
        for i, r in enumerate(results, 1):
            source = r["source"]
            score = r["score"]
            text = r["text"]
            level = r.get("doc_level", "")
            level_tag = f" [{level}]" if level else ""
            context_parts.append(
                f"--- [Source {i}: {source}{level_tag} (score: {score:.2f})] ---\n{text}"
            )

        return "\n\n".join(context_parts)

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

        response = self.client.chat(
            messages=messages,
            model=self.model,
            temperature=self.temperature,
            max_tokens=4096,
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

    def _generate_report(self) -> str:
        if not self.history:
            return "No exchanges to summarize."

        summary_prompt = (
            "Summarize this work session in 3 to 8 sentences. "
            "Mention: the topic covered, decisions made, deliverables produced, "
            "and next steps if any. Be factual and concise."
        )

        condensed = []
        for msg in self.history:
            content = msg["content"]
            if len(content) > 300:
                content = content[:300] + "..."
            condensed.append({"role": msg["role"], "content": content})

        messages = [
            {"role": "system", "content": summary_prompt},
            {"role": "user", "content": "Here are the exchanges:\n\n" + "\n".join(
                f"{'User' if m['role']=='user' else 'Agent'}: {m['content']}"
                for m in condensed
            )},
        ]

        try:
            summary = self.client.chat(
                messages=messages,
                model=self.model,
                temperature=0.3,
                max_tokens=1024,
            )
        except Exception as e:
            logger.error(f"Failed to generate summary: {e}")
            summary = "(Automatic summary unavailable -- API error)"

        filepath = save_report(
            agent_name=self.name,
            summary=summary,
            exchanges=self.history,
            actions=self.actions_log if self.actions_log else None,
            files_generated=self.files_generated if self.files_generated else None,
        )

        return f"Report saved: {filepath}"

    def _list_reports(self, agent_filter: Optional[str] = None) -> str:
        reports = list_reports(agent_filter)
        if not reports:
            return f"No report for agent '{agent_filter}'." if agent_filter else "No reports available."

        lines = ["Available reports:", ""]
        for r in reports[:20]:
            lines.append(f"  [{r['date']}] {r['agent']} -> {r['filename']}")
        total = len(reports)
        if total > 20:
            lines.append(f"  ... and {total - 20} more")
        lines.append(f"\nTotal: {total} report(s)")
        return "\n".join(lines)

    def _undo_last_report(self, agent_name: str) -> str:
        deleted = delete_last_report(agent_name)
        if deleted:
            return f"Last report deleted: {deleted}"
        return f"No report to delete for '{agent_name}'."

    def _help_text(self) -> str:
        return (
            "Available commands:\n"
            "  /save            -- Generate a session report\n"
            "  /reports [agent] -- List reports (optional: filter by agent)\n"
            "  /undo [agent]    -- Delete last report (default: current agent)\n"
            "  /clear           -- Clear conversation history\n"
            "  /history         -- Show recent messages\n"
            "  /switch          -- Switch agent\n"
            "  /help            -- Show this help\n"
        )

    def post_process(self, response: str) -> str:
        return response

    def log_action(self, action: str):
        self.actions_log.append(action)

    def log_file(self, filepath: str):
        self.files_generated.append(filepath)
