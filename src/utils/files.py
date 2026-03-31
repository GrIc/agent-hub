"""Utility functions for file operations."""

import stat
from pathlib import Path


def is_readonly(path: str | Path) -> bool:
    """Check if a file is read-only."""
    path = Path(path)
    if not path.exists():
        return False
    mode = path.stat().st_mode
    return not (mode & stat.S_IWUSR)


def make_writable(path: str | Path) -> None:
    """Make a file writable (fallback when SCM command is not configured)."""
    path = Path(path)
    if path.exists():
        current = path.stat().st_mode
        path.chmod(current | stat.S_IWUSR)


def make_readonly(path: str | Path) -> None:
    """Make a file read-only."""
    path = Path(path)
    if path.exists():
        current = path.stat().st_mode
        path.chmod(current & ~stat.S_IWUSR)


def safe_path(base: Path, relative: str) -> Path:
    """Resolve a path safely, preventing directory traversal."""
    resolved = (base / relative).resolve()
    if not str(resolved).startswith(str(base.resolve())):
        raise ValueError(f"Path traversal detected: {relative}")
    return resolved
