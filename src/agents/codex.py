"""
Codex agent -- Codebase introspection and documentation generation.

Two modes:
- Conversation: answers code questions via RAG
- Scan: browses workspace file by file, generates docs

Generated docs go to context/docs/ to enrich RAG for all agents.
"""

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.agents.base import BaseAgent

logger = logging.getLogger(__name__)

CONTEXT_DOCS_DIR = Path("context/docs")
OUTPUT_DIR = Path("output")

# Code extensions to scan (not binaries, not assets)
CODE_EXTENSIONS = {
    ".py", ".java", ".js", ".ts", ".jsx", ".tsx", ".cs",
    ".sql", ".tcl", ".jsp", ".properties",
    ".xml", ".yaml", ".yml", ".json",
    ".html", ".css", ".scss",
    ".sh", ".bat", ".cmd",
    ".md", ".txt", ".rst",
}

# Max file size to read (200KB)
MAX_FILE_SIZE = 200_000

# Max chars to send in a single LLM call (~8K tokens, safe for 32K context models)
MAX_CHUNK_FOR_LLM = 24_000


class CodexAgent(BaseAgent):
    name = "codex"

    def __init__(self, *args, workspace_path: str = "./workspace", **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = Path(workspace_path).resolve()

        # Add custom DSL extension if configured
        dsl_ext = kwargs.get("custom_dsl_ext")
        if dsl_ext and dsl_ext not in CODE_EXTENSIONS:
            CODE_EXTENSIONS.add(dsl_ext)

    def handle_command(self, cmd: str) -> Optional[str]:
        parts = cmd.strip().split(maxsplit=1)
        command = parts[0].lower()

        if command == "/scan":
            target = parts[1].strip() if len(parts) > 1 else ""
            return self._scan(target)

        if command == "/tree":
            return self._show_tree()

        if command == "/inventory":
            return self._inventory()

        return super().handle_command(cmd)

    # -- /scan: browse and document ---

    def _scan(self, target: str) -> str:
        """
        Scan files or directories and generate documentation.

        Usage:
            /scan                     -> scan entire workspace
            /scan src/main            -> scan a subdirectory
            /scan src/main/App.java   -> scan a single file
        """
        if not self.workspace.exists():
            return f"Workspace not found: {self.workspace}"

        if target:
            scan_path = self.workspace / target
        else:
            scan_path = self.workspace

        if not scan_path.exists():
            return f"Path not found: {target}"

        if scan_path.is_file():
            files = [scan_path]
        else:
            files = self._collect_code_files(scan_path)

        if not files:
            return "No code files found in this path."

        results = []
        results.append(f"Scanning {'`' + target + '`' if target else 'entire workspace'} ({len(files)} files)")

        # Group files by logical module (parent directory)
        modules: dict[str, list[Path]] = {}
        for f in files:
            try:
                relative = f.relative_to(self.workspace)
            except ValueError:
                relative = f
            module = str(relative.parent) if str(relative.parent) != "." else "root"
            modules.setdefault(module, []).append(f)

        generated_docs = []

        for module_name, module_files in modules.items():
            results.append(f"\nModule: {module_name} ({len(module_files)} files)")

            combined = self._read_module_files(module_files)

            if not combined.strip():
                results.append("  Skipped (no readable content).")
                continue

            chunks = self._split_for_llm(combined)
            results.append(f"  {len(combined)} chars, {len(chunks)} chunk(s) to analyze")

            try:
                doc = self._generate_module_doc(module_name, chunks)
                if doc:
                    filepath = self._save_doc(module_name, doc)
                    generated_docs.append(filepath)
                    results.append(f"  Doc generated: {filepath}")
                    self.log_action(f"Documentation generated: {module_name}")
                    self.log_file(filepath)
                else:
                    results.append("  No documentation produced by the LLM.")
            except Exception as e:
                results.append(f"  LLM error: {e}")
                logger.error(f"Doc generation failed for {module_name}: {e}")

        if generated_docs:
            results.append(f"\n{len(generated_docs)} doc file(s) generated in context/docs/")
            results.append("   Run /reindex for other agents to benefit.")
        else:
            results.append("\nNo documentation generated.")

        return "\n".join(results)

    def _collect_code_files(self, directory: Path) -> list[Path]:
        """Collect all code files recursively, skip junk."""
        skip_dirs = {
            "node_modules", "__pycache__", ".git", ".svn", ".hg",
            "dist", "build", ".next", "target", ".venv", "venv",
            ".idea", ".vscode", "vendor",
        }

        files = []
        for path in sorted(directory.rglob("*")):
            if not path.is_file():
                continue
            if any(part in skip_dirs or part.startswith(".") for part in path.relative_to(directory).parts[:-1]):
                continue
            if path.suffix.lower() not in CODE_EXTENSIONS:
                continue
            if path.stat().st_size > MAX_FILE_SIZE:
                continue
            files.append(path)

        return files

    def _read_module_files(self, files: list[Path]) -> str:
        """Read and concatenate files with headers."""
        parts = []
        for f in files:
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
                if content.count("\ufffd") > len(content) * 0.1:
                    continue
                relative = f.relative_to(self.workspace) if self.workspace in f.parents else f.name
                parts.append(f"\n{'='*60}\n[FILE: {relative}]\n{'='*60}\n{content}")
            except Exception as e:
                logger.debug(f"Cannot read {f}: {e}")
        return "\n".join(parts)

    def _split_for_llm(self, text: str) -> list[str]:
        """Split text into LLM-sized chunks, breaking at file boundaries."""
        if len(text) <= MAX_CHUNK_FOR_LLM:
            return [text]

        chunks = []
        current = ""

        for line in text.split("\n"):
            if len(current) + len(line) > MAX_CHUNK_FOR_LLM:
                if current:
                    chunks.append(current)
                current = line + "\n"
            else:
                current += line + "\n"

        if current.strip():
            chunks.append(current)

        return chunks

    def _generate_module_doc(self, module_name: str, chunks: list[str]) -> str:
        """Send code to LLM and get documentation back."""
        all_doc_parts = []

        for i, chunk in enumerate(chunks):
            is_first = i == 0
            is_last = i == len(chunks) - 1

            if is_first and is_last:
                instruction = (
                    f"Document the module '{module_name}'. "
                    "Produce complete documentation following the system prompt format."
                )
            elif is_first:
                instruction = (
                    f"Document the module '{module_name}' (part {i+1}/{len(chunks)}). "
                    "Start the documentation. More parts will follow."
                )
            else:
                instruction = (
                    f"Continuation of module documentation '{module_name}' (part {i+1}/{len(chunks)}). "
                    f"{'Finish the documentation.' if is_last else 'Continue.'} "
                    f"Previous context:\n{all_doc_parts[-1][:500]}..."
                )

            messages = self.build_messages(f"{instruction}\n\nSource code:\n{chunk}")

            response = self.client.chat(
                messages=messages,
                model=self.model,
                temperature=self.temperature,
                max_tokens=4096,
            )

            doc_match = re.search(r"```doc_md\s*(.*?)\s*```", response, re.DOTALL)
            if doc_match:
                all_doc_parts.append(doc_match.group(1))
            else:
                all_doc_parts.append(response)

        return "\n\n".join(all_doc_parts)

    def _save_doc(self, module_name: str, content: str) -> str:
        """Save generated documentation to context/docs/."""
        CONTEXT_DOCS_DIR.mkdir(parents=True, exist_ok=True)

        safe_name = re.sub(r"[^\w\s-]", "_", module_name).strip("_")
        safe_name = safe_name or "root"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"codex_{safe_name}_{timestamp}.md"
        filepath = CONTEXT_DOCS_DIR / filename
        filepath.write_text(content.strip(), encoding="utf-8")

        logger.info(f"Documentation saved: {filepath}")
        return str(filepath)

    # -- /inventory: quick overview ---

    def _inventory(self) -> str:
        """Quick inventory of the workspace without LLM calls."""
        if not self.workspace.exists():
            return f"Workspace not found: {self.workspace}"

        files = self._collect_code_files(self.workspace)
        if not files:
            return "No code files found in the workspace."

        by_ext: dict[str, int] = {}
        by_dir: dict[str, int] = {}
        total_size = 0

        for f in files:
            ext = f.suffix.lower()
            by_ext[ext] = by_ext.get(ext, 0) + 1
            relative = f.relative_to(self.workspace)
            top_dir = str(relative.parts[0]) if len(relative.parts) > 1 else "(root)"
            by_dir[top_dir] = by_dir.get(top_dir, 0) + 1
            total_size += f.stat().st_size

        lines = [
            f"Workspace inventory: {self.workspace}",
            f"   {len(files)} code files, {total_size / 1024:.0f} KB total",
            "",
            "By extension:",
        ]
        for ext, count in sorted(by_ext.items(), key=lambda x: -x[1]):
            lines.append(f"  {ext:12s} : {count:4d} files")

        lines.append("\nBy directory (top-level):")
        for d, count in sorted(by_dir.items(), key=lambda x: -x[1]):
            lines.append(f"  {d:20s} : {count:4d} files")

        lines.append(f"\nUse /scan [directory] to document a module.")
        return "\n".join(lines)

    # -- /tree ---

    def _show_tree(self, max_depth: int = 3) -> str:
        if not self.workspace.exists():
            return f"Workspace not found: {self.workspace}"
        lines = [f"{self.workspace}"]
        self._tree_recursive(self.workspace, lines, "", max_depth, 0)
        if len(lines) > 100:
            return "\n".join(lines[:100]) + f"\n... ({len(lines)-100} remaining entries)"
        return "\n".join(lines)

    def _tree_recursive(self, path: Path, lines: list, prefix: str, max_depth: int, depth: int):
        if depth >= max_depth:
            return
        skip = {"node_modules", "__pycache__", ".git", ".svn", "dist", "build", ".venv", "venv", ".idea", ".vscode"}
        try:
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            return
        entries = [e for e in entries if not e.name.startswith(".") and e.name not in skip]
        for i, entry in enumerate(entries):
            is_last = i == len(entries) - 1
            connector = "└── " if is_last else "├── "
            icon = "d" if entry.is_dir() else "f"
            lines.append(f"{prefix}{connector}[{icon}] {entry.name}")
            if entry.is_dir():
                ext = "    " if is_last else "│   "
                self._tree_recursive(entry, lines, prefix + ext, max_depth, depth + 1)

    # -- post_process ---

    def post_process(self, response: str) -> str:
        """Extract doc_md blocks from conversational responses too."""
        doc_match = re.search(r"```doc_md\s*(.*?)\s*```", response, re.DOTALL)
        if not doc_match:
            return response

        try:
            first_line = doc_match.group(1).strip().split("\n")[0]
            name = re.sub(r"^#+\s*", "", first_line).strip()
            name = re.sub(r"^Documentation\s*[-—]\s*", "", name, flags=re.IGNORECASE).strip()
            filepath = self._save_doc(name or "manual", doc_match.group(1))
            self.log_action(f"Documentation generated: {name}")
            self.log_file(filepath)
            return (
                f"{response}\n\n"
                f"Documentation saved: {filepath}\n"
                f"   Run /reindex for other agents to benefit."
            )
        except Exception as e:
            logger.error(f"Doc save failed: {e}")
            return f"{response}\n\nSave error: {e}"

    def _help_text(self) -> str:
        return (
            super()._help_text()
            + "\nCodex-specific commands:\n"
            "  /scan [path]    -- Scan and document workspace files/directories\n"
            "  /inventory      -- Quick overview (files, extensions, sizes)\n"
            "  /tree           -- Workspace tree\n"
            "\nExamples:\n"
            "  /inventory                    -> global stats\n"
            "  /scan                         -> document entire workspace\n"
            "  /scan src/main/java           -> document a subdirectory\n"
            "  /scan src/main/App.java       -> document a specific file\n"
            "  'How does the auth module work?' -> question via RAG\n"
            "\nDocs are saved in context/docs/ -> /reindex after.\n"
        )
