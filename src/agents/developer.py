"""
Developer agent.
Analyzes code, proposes modifications, applies after validation.
Workflow: analysis -> proposal (diff) -> validation -> apply (unlock -> edit -> lock).
"""

import json
import logging
import os
import re
import subprocess
import difflib
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.agents.base import BaseAgent

logger = logging.getLogger(__name__)
OUTPUT_DIR = Path("output")


class DeveloperAgent(BaseAgent):
    name = "developer"

    def __init__(self, *args, workspace_path: str = "./workspace", scm_config: Optional[dict] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = Path(workspace_path).resolve()
        self.scm = scm_config or {}
        self.pending_changes: Optional[dict] = None

    def handle_command(self, cmd: str) -> Optional[str]:
        parts = cmd.strip().split(maxsplit=1)
        command = parts[0].lower()

        if command == "/apply":
            return self._apply_changes()
        if command == "/diff":
            return self._show_diff()
        if command == "/show" and len(parts) > 1:
            return self._show_file(parts[1])
        if command == "/tree":
            return self._show_tree()

        return super().handle_command(cmd)

    def post_process(self, response: str) -> str:
        changes_match = re.search(r"```changes_json\s*(\{.*?\})\s*```", response, re.DOTALL)
        if not changes_match:
            return response

        try:
            self.pending_changes = json.loads(changes_match.group(1))
            diff_text = self._generate_diff_preview()
            return (
                f"{response}\n\n"
                f"{'='*60}\n"
                f"DIFF PREVIEW\n{'='*60}\n"
                f"{diff_text}\n"
                f"{'='*60}\n"
                f"Type /apply to apply these changes\n"
                f"   or continue the discussion to refine."
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Changes parsing failed: {e}")
            return f"{response}\n\nChanges parsing error: {e}"

    def _generate_diff_preview(self) -> str:
        if not self.pending_changes:
            return "No pending changes."

        diffs = []
        for change in self.pending_changes.get("changes", []):
            filepath = change.get("file", "?")
            action = change.get("action", "modify")
            desc = change.get("description", "")

            diffs.append(f"\n--- {filepath} ({action}) ---")
            diffs.append(f"# {desc}")

            if action == "modify":
                old = change.get("search", "").splitlines(keepends=True)
                new = change.get("replace", "").splitlines(keepends=True)
                diff = difflib.unified_diff(old, new, fromfile=f"a/{filepath}", tofile=f"b/{filepath}")
                diffs.append("".join(diff))
            elif action == "create":
                content = change.get("content", "")
                for line in content.splitlines()[:20]:
                    diffs.append(f"+ {line}")
                if content.count("\n") > 20:
                    diffs.append(f"  ... ({content.count(chr(10)) - 20} more lines)")
            elif action == "delete":
                diffs.append("  File will be deleted")

        return "\n".join(diffs)

    def _apply_changes(self) -> str:
        if not self.pending_changes:
            return "No pending changes. Propose modifications first."

        results = []
        changes = self.pending_changes.get("changes", [])

        for change in changes:
            filepath = change.get("file", "")
            action = change.get("action", "modify")
            full_path = self.workspace / filepath

            try:
                if action == "modify":
                    result = self._modify_file(full_path, change)
                elif action == "create":
                    result = self._create_file(full_path, change)
                elif action == "delete":
                    result = self._delete_file(full_path)
                else:
                    result = f"Unknown action: {action}"

                results.append(f"  {filepath}: {result}")
                self.log_action(f"{action} {filepath}")
            except Exception as e:
                results.append(f"  {filepath}: Error: {e}")
                logger.error(f"Failed to apply change to {filepath}: {e}")

        summary = self.pending_changes.get("summary", "")
        self.log_action(f"Changes applied: {summary}")
        self.pending_changes = None
        return "Application result:\n" + "\n".join(results)

    def _unlock_file(self, path: Path) -> None:
        unlock_cmd = self.scm.get("unlock_cmd", os.getenv("FILE_UNLOCK_CMD", ""))
        if not unlock_cmd:
            try:
                path.chmod(path.stat().st_mode | 0o200)
            except OSError:
                pass
            return

        cmd = unlock_cmd.replace("{filepath}", str(path))
        logger.info(f"Unlocking: {cmd}")
        try:
            subprocess.run(cmd, shell=True, check=True, capture_output=True, timeout=30)
        except subprocess.CalledProcessError as e:
            logger.warning(f"Unlock command failed: {e.stderr}")
            try:
                path.chmod(path.stat().st_mode | 0o200)
            except OSError:
                pass

    def _lock_file(self, path: Path) -> None:
        lock_cmd = self.scm.get("lock_cmd", os.getenv("FILE_LOCK_CMD", ""))
        if not lock_cmd:
            return
        cmd = lock_cmd.replace("{filepath}", str(path))
        logger.info(f"Locking: {cmd}")
        try:
            subprocess.run(cmd, shell=True, check=True, capture_output=True, timeout=30)
        except subprocess.CalledProcessError as e:
            logger.warning(f"Lock command failed: {e.stderr}")

    def _modify_file(self, path: Path, change: dict) -> str:
        if not path.exists():
            return f"File not found: {path}"

        content = path.read_text(encoding="utf-8", errors="replace")
        search = change.get("search", "")
        replace = change.get("replace", "")

        if search not in content:
            return f"'search' block not found. Use /show {path.relative_to(self.workspace)} to verify."

        new_content = content.replace(search, replace, 1)

        # Backup
        backup_dir = OUTPUT_DIR / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{path.name}.{ts}.bak"
        (backup_dir / backup_name).write_text(content, encoding="utf-8")

        self._unlock_file(path)
        path.write_text(new_content, encoding="utf-8")
        self._lock_file(path)

        return f"Modified (backup: backups/{backup_name})"

    def _create_file(self, path: Path, change: dict) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        content = change.get("content", "")
        path.write_text(content, encoding="utf-8")
        self.log_file(str(path))
        return "Created"

    def _delete_file(self, path: Path) -> str:
        if not path.exists():
            return "File already absent"
        backup_dir = OUTPUT_DIR / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{path.name}.{ts}.bak"
        (backup_dir / backup_name).write_text(
            path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8"
        )
        self._unlock_file(path)
        path.unlink()
        return f"Deleted (backup: backups/{backup_name})"

    def _show_file(self, filepath: str) -> str:
        path = self.workspace / filepath.strip()
        if not path.exists():
            return f"File not found: {filepath}"
        if not path.is_file():
            return f"Not a file: {filepath}"
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()
            if len(lines) > 200:
                truncated = "\n".join(lines[:200])
                return f"{filepath} ({len(lines)} lines, truncated):\n\n{truncated}\n\n... ({len(lines)-200} remaining lines)"
            return f"{filepath} ({len(lines)} lines):\n\n{content}"
        except Exception as e:
            return f"Read error: {e}"

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
        try:
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            return

        entries = [
            e for e in entries
            if not e.name.startswith(".") and e.name not in ("node_modules", "__pycache__", ".git")
        ]
        for i, entry in enumerate(entries):
            is_last = i == len(entries) - 1
            connector = "└── " if is_last else "├── "
            icon = "d" if entry.is_dir() else "f"
            lines.append(f"{prefix}{connector}[{icon}] {entry.name}")
            if entry.is_dir():
                extension = "    " if is_last else "│   "
                self._tree_recursive(entry, lines, prefix + extension, max_depth, depth + 1)

    def _show_diff(self) -> str:
        if not self.pending_changes:
            return "No pending changes."
        return self._generate_diff_preview()

    def _help_text(self) -> str:
        return (
            super()._help_text()
            + "\nDeveloper commands:\n"
            "  /apply          -- Apply proposed changes\n"
            "  /diff           -- Redisplay pending diff\n"
            "  /show <file>    -- Display a workspace file\n"
            "  /tree           -- Workspace tree\n"
        )


# Backward compatibility alias
TechAgent = DeveloperAgent
