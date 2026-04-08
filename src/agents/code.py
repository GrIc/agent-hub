"""
Code agent.
For each task, produces .diff files applicable via `git apply`.
Workflow: analysis -> diff generation -> validation -> apply.
"""

import logging
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.agents.base import BaseAgent

logger = logging.getLogger(__name__)
OUTPUT_DIR = Path("output")
DIFFS_DIR = OUTPUT_DIR / "diffs"


class CodeAgent(BaseAgent):
    name = "code"

    def __init__(self, *args, workspace_path: str = "./workspace",
                 scm_config: Optional[dict] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = Path(workspace_path).resolve()
        self.scm = scm_config or {}
        self.pending_diff: Optional[str] = None
        self.pending_diff_path: Optional[Path] = None

    def handle_command(self, cmd: str) -> Optional[str]:
        parts = cmd.strip().split(maxsplit=1)
        command = parts[0].lower()

        if command == "/apply":
            return self._apply_diff()
        if command == "/diff":
            return self._show_pending_diff()
        if command == "/diffs":
            return self._list_diffs()
        if command == "/show" and len(parts) > 1:
            return self._show_file(parts[1])
        if command == "/tree":
            return self._show_tree()

        return super().handle_command(cmd)

    def post_process(self, response: str) -> str:
        """Extract diff blocks from the response and save as .diff files."""
        # Look for ```diff blocks
        diff_match = re.search(r"```diff\s*\n([\s\S]*?)```", response)
        if not diff_match:
            return response

        diff_content = diff_match.group(1).strip()
        if not diff_content:
            return response

        try:
            DIFFS_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            diff_path = DIFFS_DIR / f"change_{ts}.diff"
            diff_path.write_text(diff_content + "\n", encoding="utf-8")

            self.pending_diff = diff_content
            self.pending_diff_path = diff_path
            self.log_action(f"Diff saved: {diff_path}")
            self.log_file(str(diff_path))

            return (
                f"{response}\n\n"
                f"{'='*60}\n"
                f"Diff saved: {diff_path}\n"
                f"{'='*60}\n"
                f"  /apply  -- apply via `git apply` in workspace\n"
                f"  /diff   -- redisplay the pending diff\n"
                f"  /diffs  -- list all saved diffs\n"
                f"  or continue the discussion to refine."
            )
        except Exception as e:
            logger.error(f"Diff save failed: {e}")
            return f"{response}\n\nDiff save error: {e}"

    def _apply_diff(self) -> str:
        """Apply the pending diff via `git apply`."""
        if not self.pending_diff_path or not self.pending_diff_path.exists():
            return "No pending diff. Generate a diff first."

        try:
            # Dry-run check first
            result = subprocess.run(
                ["git", "apply", "--check", str(self.pending_diff_path)],
                cwd=str(self.workspace),
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                return (
                    f"Diff check failed (dry-run):\n{result.stderr}\n\n"
                    f"The diff cannot be applied cleanly. Refine and try again."
                )

            # Actually apply
            result = subprocess.run(
                ["git", "apply", str(self.pending_diff_path)],
                cwd=str(self.workspace),
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                self.log_action(f"Applied diff: {self.pending_diff_path.name}")
                applied_path = self.pending_diff_path
                self.pending_diff = None
                self.pending_diff_path = None
                return f"Diff applied successfully: {applied_path.name}"
            else:
                return f"git apply failed:\n{result.stderr}"

        except FileNotFoundError:
            return "Error: `git` is not installed or not in PATH."
        except subprocess.TimeoutExpired:
            return "Error: git apply timed out."
        except Exception as e:
            return f"Error applying diff: {e}"

    def _show_pending_diff(self) -> str:
        """Redisplay the pending diff."""
        if not self.pending_diff:
            return "No pending diff."
        return f"```diff\n{self.pending_diff}\n```"

    def _list_diffs(self) -> str:
        """List all saved diff files."""
        if not DIFFS_DIR.exists():
            return "No diffs directory yet."
        diffs = sorted(DIFFS_DIR.glob("*.diff"), reverse=True)
        if not diffs:
            return "No diff files found."
        lines = ["Saved diffs:", ""]
        for d in diffs[:20]:
            size = d.stat().st_size
            lines.append(f"  {d.name} ({size} bytes)")
        return "\n".join(lines)

    def _show_file(self, filepath: str) -> str:
        """Display a workspace file."""
        full = self.workspace / filepath
        if not full.exists():
            return f"File not found: {filepath}"
        try:
            content = full.read_text(encoding="utf-8", errors="replace")
            if len(content) > 5000:
                content = content[:5000] + "\n[... truncated]"
            return f"```\n{content}\n```"
        except Exception as e:
            return f"Cannot read {filepath}: {e}"

    def _show_tree(self) -> str:
        """Show workspace directory tree."""
        if not self.workspace.exists():
            return f"Workspace not found: {self.workspace}"
        lines = [f"Workspace: {self.workspace}", ""]
        self._tree_recursive(self.workspace, lines, "", max_depth=3)
        return "\n".join(lines)

    def _tree_recursive(self, path, lines, prefix, max_depth, depth=0):
        if depth >= max_depth:
            return
        skip = {"node_modules", "__pycache__", ".git", ".svn", "dist", "build",
                ".venv", "venv", ".vectordb", ".idea", ".vscode"}
        try:
            entries = sorted(path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
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

    def _help_text(self) -> str:
        return (
            super()._help_text()
            + "\nCode commands:\n"
            "  /apply          -- Apply pending diff via `git apply`\n"
            "  /diff           -- Redisplay pending diff\n"
            "  /diffs          -- List all saved diff files\n"
            "  /show <file>    -- Display a workspace file\n"
            "  /tree           -- Workspace tree\n"
        )


# Backward compatibility alias
TechAgent = CodeAgent