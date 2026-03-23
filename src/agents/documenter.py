"""
Documenter agent -- produces technical documentation and diagrams of the existing codebase.
Not project-scoped: works globally on the code indexed in the RAG.
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.agents.base import BaseAgent

logger = logging.getLogger(__name__)
OUTPUT_DIR = Path("output/documentation")


class DocumenterAgent(BaseAgent):
    name = "documenter"

    def handle_command(self, cmd: str) -> Optional[str]:
        parts = cmd.strip().split(maxsplit=1)
        command = parts[0].lower()

        if command == "/overview":
            return self.chat("Generate a high-level architecture overview of the entire codebase based on what you know from the RAG context. Use the doc_output format.")
        if command == "/classes" and len(parts) > 1:
            return self.chat(f"Generate a Mermaid class diagram for the module/area: {parts[1]}. Use the doc_output format.")
        if command == "/sequence" and len(parts) > 1:
            return self.chat(f"Generate a Mermaid sequence diagram for this flow: {parts[1]}. Use the doc_output format.")
        if command == "/datamodel":
            area = parts[1] if len(parts) > 1 else "the main data model"
            return self.chat(f"Generate a data model / ER diagram for: {area}. Use the doc_output format.")
        if command == "/components":
            return self.chat("Generate a component interaction map showing how the main modules and services connect. Use the doc_output format.")
        if command == "/reference" and len(parts) > 1:
            return self.chat(f"Generate a detailed technical reference for the module: {parts[1]}. Use the doc_output format.")

        return super().handle_command(cmd)

    def post_process(self, response: str) -> str:
        match = re.search(r"```doc_output\s*(.*?)\s*```", response, re.DOTALL)
        if not match:
            return response

        try:
            content = match.group(1).strip()
            filepath = self._save_doc(content)
            self.log_action(f"Documentation generated: {filepath}")
            self.log_file(filepath)
            return f"{response}\n\nDocumentation saved: {filepath}"
        except Exception as e:
            logger.error(f"Save failed: {e}")
            return f"{response}\n\nSave error: {e}"

    def _save_doc(self, content: str) -> str:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        title = "doc"
        first_line = content.split("\n")[0]
        if first_line.startswith("#"):
            title = re.sub(r"^#+\s*", "", first_line).strip()
        safe = re.sub(r"[^\w\s-]", "", title)[:50].strip().replace(" ", "_") or "doc"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = OUTPUT_DIR / f"{safe}_{ts}.md"
        filepath.write_text(content, encoding="utf-8")
        logger.info(f"Documentation saved: {filepath}")
        return str(filepath)

    def _help_text(self) -> str:
        return (
            super()._help_text()
            + "\nDocumenter commands:\n"
            "  /overview              -- Architecture overview of the codebase\n"
            "  /classes <module>      -- Class diagram for a module\n"
            "  /sequence <flow>       -- Sequence diagram for a flow\n"
            "  /datamodel [area]      -- Data model / ER diagram\n"
            "  /components            -- Component interaction map\n"
            "  /reference <module>    -- Technical reference for a module\n"
            "\nExamples:\n"
            "  /classes auth          -- Class diagram of the auth module\n"
            "  /sequence login flow   -- Sequence diagram of login\n"
            "  /datamodel Part        -- ER diagram around Part type\n"
        )
