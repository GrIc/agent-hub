"""
Codex agent -- Codebase introspection and documentation generation.

Two modes:
- Conversation: answers code questions via RAG
- Scan: browses workspace file by file, generates docs

Generated docs go to context/docs/ to enrich RAG for all agents.
"""

import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.agents.base import BaseAgent
from src.rag.grounding import (
    GROUNDING_INSTRUCTION,
    ABSTAIN_TOKEN,
    prepend_grounding,
    contains_abstain,
    load_noise_filter,
)
from src.rag.identifiers import extract_identifiers, detect_language
from src.rag.quality_report import record_file_quality

logger = logging.getLogger(__name__)

CONTEXT_DOCS_DIR = Path("context/docs")
OUTPUT_DIR = Path("output")
GROUNDING_VERSION = "1.0.0"

# Fallback defaults — overridden at instantiation by config.yaml [scanning] via scan_config.
# Edit config.yaml, not here.
CODE_EXTENSIONS = {
    ".py", ".java", ".js", ".ts", ".jsx", ".tsx", ".cs",
    ".sql", ".properties",
    ".xml", ".yaml", ".yml", ".json",
    ".html", ".css", ".scss",
    ".cpp", ".h", ".hpp", ".c", ".go", ".rb", ".php",
    ".sh", ".bash", ".zsh", ".bat", ".cmd",
    ".md", ".txt", ".rst",
}

MAX_FILE_SIZE = 200_000  # 200KB

# Max chars to send in a single LLM call (~8K tokens, safe for 32K context models)
MAX_CHUNK_FOR_LLM = 24_000

# How many times to try getting a complete response for a single chunk
MAX_COMPLETION_ATTEMPTS = 4

# ---------------------------------------------------------------------------
# Grounding instruction appended to EVERY codex LLM call.
# This is the primary defense against hallucination.
# ---------------------------------------------------------------------------
GROUNDING_INSTRUCTION = """
GROUNDING RULES (mandatory — violations corrupt the entire documentation system):
- ONLY describe classes, methods, variables, and imports that appear VERBATIM in the
  source code above. If a name does not appear in the source, do NOT mention it.
- NEVER infer, extrapolate, or invent functionality. If the source code does not show
  a behavior, do not describe it.
- NEVER add classes, methods, fields, or imports that are not in the source.
- If the code is too complex to fully document from what is visible, write
  "[NOT VISIBLE IN PROVIDED CODE]" for the unclear parts.
- If the module is simple, produce a SHORT document. Do not pad with guesses.
- Every file path you cite must match exactly what appears in the [FILE: ...] headers.
"""


class CodexAgent(BaseAgent):
    name = "codex"

    def __init__(self, *args, workspace_path: str = "./workspace", **kwargs):
        # FIX: pop custom_dsl_ext BEFORE calling super().__init__() to avoid
        # passing an unexpected keyword argument to BaseAgent.__init__().
        dsl_ext = kwargs.pop("custom_dsl_ext", None)
        scan_cfg = kwargs.pop("scan_config", {})
        super().__init__(*args, **kwargs)
        self.workspace = Path(workspace_path).resolve()

        if scan_cfg.get("extensions"):
            CODE_EXTENSIONS.clear()
            CODE_EXTENSIONS.update(scan_cfg["extensions"])
        if scan_cfg.get("max_file_size") is not None:
            global MAX_FILE_SIZE
            MAX_FILE_SIZE = scan_cfg["max_file_size"]
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

            # Incremental check: skip if doc exists and no source is newer
            doc_path = self._doc_path_for(module_name)
            if doc_path.exists():
                doc_mtime = doc_path.stat().st_mtime
                newest_src = max((f.stat().st_mtime for f in module_files if f.exists()), default=0)
                if newest_src <= doc_mtime:
                    results.append(f"  Skipped (doc up-to-date).")
                    continue

            combined = self._read_module_files(module_files)

            if not combined.strip():
                results.append("  Skipped (no readable content).")
                continue

            chunks = self._split_for_llm(combined)
            results.append(f"  {len(combined)} chars, {len(chunks)} chunk(s) to analyze")

            try:
                # Hardened generation with reject-retry-abstain
                max_retries = self.extra_params.get("config", {}).get("grounding", {}).get("codex_max_retries", 3)
                doc, quality_meta = self._generate_doc_for_file_strict(
                    module_name, combined, max_retries=max_retries
                )
                
                if doc:
                    # Record quality metrics
                    record_file_quality(module_name, quality_meta)
                    
                    if not quality_meta.get("abstained", False):
                        filepath = self._save_doc(module_name, doc)
                        generated_docs.append(filepath)
                        results.append(f"  Doc generated: {filepath}")
                        self.log_action(f"Documentation generated: {module_name}")
                        self.log_file(filepath)
                    else:
                        results.append(f"  Skipped (abstained): {module_name}")
                        logger.warning(f"[Codex] Abstained for {module_name}: {quality_meta.get('hallucinated_names_last_attempt', [])}")
                else:
                    results.append("  No documentation produced by the LLM.")
                    logger.warning(f"[Codex] Empty doc for {module_name}")
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
        """Collect all code files recursively, skip junk. Follows symlinks."""
        skip_dirs = {
            "node_modules", "__pycache__", ".git", ".svn", ".hg",
            "dist", "build", ".next", "target", ".venv", "venv",
            ".idea", ".vscode", "vendor",
        }

        files = []
        for dirpath, dirnames, filenames in os.walk(directory, followlinks=True):
            # Filter in-place to prevent descending into skip dirs
            dirnames[:] = [d for d in dirnames if d not in skip_dirs and not d.startswith(".")]
            for fname in sorted(filenames):
                path = Path(dirpath) / fname
                if path.suffix.lower() not in CODE_EXTENSIONS:
                    continue
                if path.stat().st_size > MAX_FILE_SIZE:
                    continue
                files.append(path)

        return sorted(files)

    def _doc_path_for(self, module_name: str) -> Path:
        """Return the deterministic doc path for a module (no timestamp)."""
        safe_name = re.sub(r"[^\w\s-]", "_", module_name).strip("_") or "root"
        return CONTEXT_DOCS_DIR / f"codex_{safe_name}.md"

    def _read_module_files(self, files: list[Path]) -> str:
        """Read and concatenate files with headers."""
        parts = []
        for f in files:
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
                if content.count("\ufffd") > len(content) * 0.1:
                    continue
                try:
                    relative = f.relative_to(self.workspace)
                except ValueError:
                    relative = f.name
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
            try:
                relative = f.relative_to(self.workspace)
            except ValueError:
                relative = f
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

    def _save_doc(self, module_name: str, content: str) -> str:
        """Save generated documentation to context/docs/."""
        try:
            CONTEXT_DOCS_DIR.mkdir(parents=True, exist_ok=True)
            filepath = self._doc_path_for(module_name)
            logger.info(f"[Codex] Writing doc to: {filepath.resolve()}")
            filepath.write_text(content.strip(), encoding="utf-8")
            logger.info(f"Documentation saved: {filepath}")
            return str(filepath)
        except Exception as e:
            logger.error(f"[Codex] _save_doc FAILED for {module_name}: {e}")
            raise

    # -- Validation: detect hallucinated names ---

    def _validate_doc(
        self,
        doc_text: str,
        known_ids: set[str],
        noise: frozenset[str],
    ) -> list[str]:
        """Return list of names mentioned in doc_text that are not in known_ids ∪ noise.

        Scans:
          - backtick-quoted tokens
          - CamelCase tokens >= 4 chars
          - snake_case tokens >= 4 chars
          - dotted paths (e.g. com.example.Foo or my.module.bar)

        Excludes: tokens that match common English words via a small built-in stopword
        list (don't reinvent NLTK; ~50 words is enough for this scope).
        """
        # Built-in stopwords to avoid false positives on common English words
        STOPWORDS = {
            "the", "and", "for", "with", "from", "this", "that", "these", "those",
            "are", "was", "were", "been", "have", "has", "had", "will", "would",
            "could", "should", "may", "might", "must", "can", "its", "their", "our",
            "your", "you", "they", "them", "then", "than", "there", "here", "when",
            "where", "what", "which", "who", "how", "why", "some", "any", "all",
            "each", "every", "both", "either", "neither", "such", "only", "also",
            "very", "just", "even", "well", "back", "still", "again", "once", "twice"
        }
        
        # Extract candidate names using multiple patterns
        candidates = set()
        
        # Backtick-quoted identifiers
        candidates.update(re.findall(r'`([^`\s]+)`', doc_text))
        
        # Bolded identifiers (LLM sometimes bolds class names)
        candidates.update(re.findall(r'\*\*([A-Z][a-zA-Z0-9_]+)\*\*', doc_text))
        
        # CamelCase/PascalCase identifiers >= 4 chars
        candidates.update(m.group(1) for m in re.finditer(r'\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b', doc_text) if len(m.group(1)) >= 4)
        
        # snake_case identifiers >= 4 chars
        candidates.update(m.group(1) for m in re.finditer(r'\b([a-z_][a-z0-9_]{3,})\b', doc_text) if len(m.group(1)) >= 4)
        
        # Dotted paths (Java packages, Python modules, etc.)
        candidates.update(re.findall(r'\b([a-z0-9_]+(?:\.[a-z0-9_]+)+)\b', doc_text))
        
        # Clean candidates: remove parentheses, brackets, etc.
        cleaned = set()
        for cand in candidates:
            clean = cand.replace("()", "").replace("[]", "").split(".")[0]
            if clean and len(clean) >= 2:  # Minimum length after cleaning
                cleaned.add(clean)
        
        # Filter out stopwords and noise
        filtered = [c for c in cleaned if c.lower() not in STOPWORDS and c not in noise]
        
        # Check which filtered names are not in known identifiers
        unknown = [name for name in filtered if name not in known_ids]
        
        return unknown

    def _generate_doc_for_file_strict(
        self,
        file_path: str,
        source_code: str,
        max_retries: int = 3,
    ) -> tuple[str, dict]:
        """Generate a doc with grounding + reject-retry. Returns (doc, quality_meta).

        quality_meta = {
            "attempts": int,
            "abstained": bool,
            "hallucinated_names_last_attempt": list[str],
            "validation_passed": bool,
            "g_version": str,
        }
        """
        language = detect_language(file_path)
        known_ids = extract_identifiers(source_code, language)
        
        # Get config from extra_params (standard pattern in BaseAgent)
        config = self.extra_params.get("config", {})
        noise = load_noise_filter(config)

        last_doc = ""
        last_hallucinated: list[str] = []
        for attempt in range(max_retries):
            # progressively stricter prompts on retry
            extra = ""
            if attempt > 0 and last_hallucinated:
                extra = (
                    f"\n\nIMPORTANT: your previous attempt mentioned these names "
                    f"that do NOT exist in the source: {last_hallucinated}. "
                    f"Remove them and any sentence that references them. "
                    f"If you cannot describe the file without using these names, "
                    f"write {ABSTAIN_TOKEN} and stop."
                )
            system = prepend_grounding(self.get_system_prompt() + extra)
            # temperature pinned low for retries
            temp = config.get("grounding", {}).get("codex_temperature_first_attempt", 0.1) if attempt == 0 else config.get("grounding", {}).get("codex_temperature_retry", 0.0)
            # token cap from config
            max_tokens = config.get("grounding", {}).get("codex_max_tokens", 1500)
            
            doc = self.client.chat(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": source_code},
                ],
                model=self.model,
                temperature=temp,
                max_tokens=max_tokens,
                complete=True,
            )
            last_doc = doc

            if contains_abstain(doc):
                quality_meta = {
                    "attempts": attempt + 1,
                    "abstained": True,
                    "hallucinated_names_last_attempt": [],
                    "validation_passed": True,
                    "g_version": GROUNDING_VERSION,
                }
                return doc, quality_meta

            hallucinated = self._validate_doc(doc, known_ids, noise)
            if not hallucinated:
                quality_meta = {
                    "attempts": attempt + 1,
                    "abstained": False,
                    "hallucinated_names_last_attempt": [],
                    "validation_passed": True,
                    "g_version": GROUNDING_VERSION,
                }
                return doc, quality_meta
            last_hallucinated = hallucinated

        # all retries exhausted: emit abstain doc
        abstain_doc = (
            f"# {Path(file_path).name}\n\n"
            f"{ABSTAIN_TOKEN}\n\n"
            f"Codex could not produce a grounded description for this file after "
            f"{max_retries} attempts. Hallucinated names in last attempt: "
            f"{last_hallucinated[:10]}. The file is excluded from the synthesis pyramid "
            f"and tagged in quality_report.json."
        )
        quality_meta = {
            "attempts": max_retries,
            "abstained": True,
            "hallucinated_names_last_attempt": last_hallucinated,
            "validation_passed": False,
            "g_version": GROUNDING_VERSION,
        }
        return abstain_doc, quality_meta
