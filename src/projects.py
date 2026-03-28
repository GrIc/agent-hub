"""
Project manager — handles project isolation and output versioning.

Each project has:
  projects/{name}/notes/     <- raw input (notes, meeting minutes)
  projects/{name}/outputs/   <- versioned agent outputs (requirements_v1.md, ...)
  projects/{name}/reports/   <- conversation reports per agent
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROJECTS_DIR = Path("projects")


class Project:
    """Represents a project with isolated notes, outputs, and reports."""

    def __init__(self, name: str):
        self.name = name
        self.root = PROJECTS_DIR / name
        self.notes_dir = self.root / "notes"
        self.outputs_dir = self.root / "outputs"
        self.reports_dir = self.root / "reports"

    def ensure_dirs(self):
        """Create project directories if they don't exist."""
        for d in [self.notes_dir, self.outputs_dir, self.reports_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def exists(self) -> bool:
        return self.root.exists()

    # -- Versioned outputs ---

    def save_output(self, doc_type: str, content: str) -> tuple[str, int]:
        """
        Save a versioned output document.
        doc_type: requirements, specifications, roadmap, architecture, deck
        Returns (filepath, version_number).
        """
        self.ensure_dirs()
        version = self._next_version(doc_type)
        filename = f"{doc_type}_v{version}.md"
        filepath = self.outputs_dir / filename
        filepath.write_text(content, encoding="utf-8")
        logger.info(f"[Project:{self.name}] Saved {filename}")
        return str(filepath), version

    def load_latest_output(self, doc_type: str) -> Optional[tuple[str, int]]:
        """Load the latest version of a document type. Returns (content, version) or None."""
        version = self._latest_version(doc_type)
        if version == 0:
            return None
        filepath = self.outputs_dir / f"{doc_type}_v{version}.md"
        if filepath.exists():
            return filepath.read_text(encoding="utf-8"), version
        return None

    def load_output_version(self, doc_type: str, version: int) -> Optional[str]:
        """Load a specific version."""
        filepath = self.outputs_dir / f"{doc_type}_v{version}.md"
        if filepath.exists():
            return filepath.read_text(encoding="utf-8")
        return None

    def list_versions(self, doc_type: str) -> list[dict]:
        """List all versions of a document type."""
        versions = []
        for f in sorted(self.outputs_dir.glob(f"{doc_type}_v*.md")):
            match = re.search(rf"{doc_type}_v(\d+)\.md", f.name)
            if match:
                v = int(match.group(1))
                stat = f.stat()
                versions.append({
                    "version": v,
                    "filename": f.name,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                })
        return versions

    def rollback_output(self, doc_type: str, to_version: int) -> bool:
        """Delete all versions after to_version."""
        deleted = 0
        for f in self.outputs_dir.glob(f"{doc_type}_v*.md"):
            match = re.search(rf"{doc_type}_v(\d+)\.md", f.name)
            if match and int(match.group(1)) > to_version:
                f.unlink()
                deleted += 1
        logger.info(f"[Project:{self.name}] Rolled back {doc_type} to v{to_version}, deleted {deleted} versions")
        return deleted > 0

    def _next_version(self, doc_type: str) -> int:
        return self._latest_version(doc_type) + 1

    def _latest_version(self, doc_type: str) -> int:
        max_v = 0
        for f in self.outputs_dir.glob(f"{doc_type}_v*.md"):
            match = re.search(rf"{doc_type}_v(\d+)\.md", f.name)
            if match:
                max_v = max(max_v, int(match.group(1)))
        return max_v

    # -- All available outputs (latest of each type) ---

    def get_all_latest_outputs(self) -> dict[str, tuple[str, int]]:
        """Get the latest version of each document type. Returns {type: (content, version)}."""
        types_found = set()
        for f in self.outputs_dir.glob("*_v*.md"):
            match = re.match(r"(.+)_v\d+\.md", f.name)
            if match:
                types_found.add(match.group(1))

        result = {}
        for doc_type in types_found:
            data = self.load_latest_output(doc_type)
            if data:
                result[doc_type] = data
        return result

    # -- Reports (per-agent conversation CRs) ---

    def get_reports_dir(self) -> Path:
        self.ensure_dirs()
        return self.reports_dir


def list_projects() -> list[str]:
    """List all available projects."""
    if not PROJECTS_DIR.exists():
        return []
    return sorted(
        d.name for d in PROJECTS_DIR.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    )


def get_or_create_project(name: str) -> Project:
    """Get an existing project or create a new one."""
    project = Project(name)
    project.ensure_dirs()
    return project
