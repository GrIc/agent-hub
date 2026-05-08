"""Git-aware primitives for the changelog system.

Wraps subprocess calls to git. No GitPython dependency to keep the install lean.

API:
    last_indexed_sha() -> str | None
    set_last_indexed_sha(sha: str)
    new_commits_since(sha: str | None) -> list[Commit]
    files_changed(sha: str) -> list[FileChange]
    diff_for_commit(sha: str) -> str

Where:
    Commit = NamedTuple(sha, author, date, subject, body)
    FileChange = NamedTuple(path, status, insertions, deletions)
"""

import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# State file for last-indexed SHA tracking
STATE_DIR = Path("context/temporal")
STATE_FILE = STATE_DIR / "state.json"


@dataclass(frozen=True)
class Commit:
    """Immutable representation of a git commit."""
    sha: str
    author: str
    date: str  # ISO 8601 timestamp
    subject: str
    body: str = ""

    @property
    def short_sha(self) -> str:
        """First 7 characters of the SHA for display."""
        return self.sha[:7]


@dataclass
class FileChange:
    """Representation of a file change within a commit."""
    path: str
    status: str  # A (added), M (modified), D (deleted), R (renamed)
    insertions: int = 0
    deletions: int = 0


def ensure_state_dir() -> None:
    """Create the state directory if it doesn't exist."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def last_indexed_sha(state_path: Optional[Path] = None) -> Optional[str]:
    """Return the last indexed commit SHA, or None if not set.

    Args:
        state_path: Optional custom path to the state file.
            Defaults to context/temporal/state.json.

    Returns:
        The full SHA string, or None if no state exists.
    """
    path = state_path or STATE_FILE
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        return state.get("last_indexed_sha")
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Cannot read state file {path}: {e}")
        return None


def set_last_indexed_sha(sha: str, state_path: Optional[Path] = None) -> None:
    """Save the last indexed commit SHA.

    Args:
        sha: The full commit SHA to save.
        state_path: Optional custom path to the state file.
    """
    ensure_state_dir()
    path = state_path or STATE_FILE
    state = {
        "last_indexed_sha": sha,
        "last_run_at": _iso_now(),
    }
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.debug(f"Saved last_indexed_sha: {sha[:7]}")


def _iso_now() -> str:
    """Return the current UTC time in ISO 8601 format."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _git(*args: str) -> subprocess.CompletedProcess:
    """Execute a git command and return the result.

    Raises subprocess.CalledProcessError on non-zero exit.
    """
    result = subprocess.run(
        ["git", "-C", ".", "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Not a git repository. Run 'git init' or set WORKSPACE_PATH to a git repo."
        )

    cmd = ["git", "-C", "."] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


def new_commits_since(
    sha: Optional[str],
    *,
    max_commits: int = 100,
    repo: Optional[Path] = None,
) -> list[Commit]:
    """List new commits in chronological order.

    Args:
        sha: If provided, return commits after this SHA.
            If None, return the last max_commits from HEAD.
        max_commits: Maximum number of commits to return (default: 100).
            Used only when sha is None.
        repo: Unused placeholder for API compatibility with the spec.
            Always uses the current working directory.

    Returns:
        List of Commit objects in chronological order (oldest first).
    """
    # Use ASCII unit separator (0x1f) as field delimiter.
    # This control character won't appear in normal git output.
    FS = "\x1f"  # Field Separator — between fields
    fmt = f"%H{FS}%an{FS}%aI{FS}%s{FS}%b"

    args = [
        "log",
        "--reverse",
        f"--format={fmt}",
        "--diff-filter=ACDMR",  # only show commits with file changes
    ]

    if sha:
        args.append(f"{sha}..HEAD")
    else:
        args.append(f"-n{max_commits}")

    result = _git(*args)
    if result.returncode != 0:
        if sha and "bad revision" in result.stderr:
            logger.info(f"No commits found after SHA {sha[:7]}")
            return []
        logger.warning(f"git log failed: {result.stderr.strip()}")
        return []

    text = result.stdout.strip()
    if not text:
        return []

    commits = []
    # Split by newline (git puts each record on its own line)
    records = text.split("\n")
    for record in records:
        record = record.strip()
        if not record:
            continue

        # Parse: SHA<FS>author<FS>date<FS>subject<FS>body
        parts = record.split(FS)
        if len(parts) < 4:
            continue

        try:
            commit_sha = parts[0].strip()
            author = parts[1].strip() if len(parts) > 1 else "unknown"
            date = parts[2].strip() if len(parts) > 2 else ""
            subject = parts[3].strip() if len(parts) > 3 else ""
            body = parts[4].strip() if len(parts) > 4 else ""

            # Clean up any trailing whitespace from body
            body = body.rstrip()

            commits.append(Commit(
                sha=commit_sha,
                author=author,
                date=date,
                subject=subject,
                body=body,
            ))
        except (IndexError, ValueError) as e:
            logger.warning(f"Skipping malformed commit record: {e}")
            continue

    return commits


def files_changed(sha: str) -> list[FileChange]:
    """Return the list of files changed in a commit.

    Args:
        sha: The full commit SHA.

    Returns:
        List of FileChange objects.
    """
    # Use porcelain status for reliable parsing
    result = _git("show", "--stat=255", "--format=", sha)
    if result.returncode != 0:
        logger.warning(f"git show --stat failed for {sha[:7]}: {result.stderr.strip()}")
        return []

    changes = []
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if not line or "commit" in line:
            continue

        # Format: " filename | N +/- "
        # Example: " src/main.py | 5 +++-- "
        # Or:     " docs/file.md | 150 ++++++++++++++++++... "
        parts = line.split("|")
        if len(parts) < 2:
            continue

        file_part = parts[0].strip()
        stats_part = parts[1].strip()

        # Parse insertions/deletions from stats
        # The stats part looks like: "5 +++--" or "150 +++++++++++++++++++..."
        # Count + and - characters (ignoring the total number)
        insertions = stats_part.count("+")
        deletions = stats_part.count("-")

        # Determine status from the file name
        # Git --stat doesn't give status directly, so we check with diff-name-only
        status = _detect_file_status(sha, file_part)

        changes.append(FileChange(
            path=file_part,
            status=status,
            insertions=insertions,
            deletions=deletions,
        ))

    return changes


def _detect_file_status(sha: str, filepath: str) -> str:
    """Detect the change type (A/M/D/R) for a file in a commit.

    Args:
        sha: The commit SHA.
        filepath: The file path.

    Returns:
        One of 'A', 'M', 'D', 'R'.
    """
    # For the root commit, use --root
    if sha == "HEAD" or sha.endswith("HEAD"):
        result = _git("diff", "--name-status", "-r", "--root", sha)
    else:
        # Check if this is the root commit
        parents_result = _git("rev-parse", f"{sha}^@")
        if parents_result.returncode != 0 or "fatal" in parents_result.stdout.lower():
            # Root commit
            result = _git("diff", "--name-status", "-r", "--root", sha)
        else:
            result = _git("diff", "--name-status", "-r", f"{sha}^..{sha}")

    if result.returncode != 0:
        return "M"  # fallback to modified

    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        # Format: A\tfilename or D\tfilename or M\tfilename
        parts = line.split("\t", 1)
        if len(parts) >= 2 and parts[1] == filepath:
            return parts[0]

    return "M"  # fallback


def diff_for_commit(
    sha: str,
    *,
    max_lines: int = 5000,
) -> str:
    """Return the unified diff for a commit, truncated if too large.

    Args:
        sha: The full commit SHA.
        max_lines: Maximum number of diff lines to return.

    Returns:
        The unified diff text, with a [truncated] note if capped.
    """
    result = _git("diff", f"{sha}^..{sha}")
    if result.returncode != 0:
        # For the first commit (no parent), diff against empty
        result = _git("diff", "--root", sha)

    if result.returncode != 0:
        logger.warning(f"git diff failed for {sha[:7]}: {result.stderr.strip()}")
        return ""

    diff_text = result.stdout
    lines = diff_text.splitlines()

    if len(lines) <= max_lines:
        return diff_text

    # Truncate with summary
    truncated = lines[:max_lines]
    truncated.append(f"\n--- [truncated: {len(lines) - max_lines} lines omitted] ---")
    return "\n".join(truncated)


def current_head() -> Optional[str]:
    """Return the current HEAD SHA, or None if not in a git repo."""
    result = _git("rev-parse", "HEAD")
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def commit_url(sha: str, base_url: Optional[str] = None) -> Optional[str]:
    """Construct a URL to the commit on the remote hosting service.

    Args:
        sha: The full commit SHA.
        base_url: Optional explicit URL base (e.g. "https://github.com/org/repo").
            If not provided, tries to derive from git remote origin.

    Returns:
        The commit URL, or None if it cannot be constructed.
    """
    if base_url:
        url_base = base_url.rstrip("/")
    else:
        # Try to get the remote URL
        result = _git("remote", "get-url", "origin")
        if result.returncode != 0:
            return None
        remote_url = result.stdout.strip()

        # Convert git@github.com:org/repo.git to https://github.com/org/repo
        if remote_url.startswith("git@"):
            remote_url = remote_url.replace(":", "/").replace("git@", "https://")
        url_base = remote_url.rstrip(".git").rstrip("/")

    short_sha = sha[:7]
    # Detect hosting provider
    if "github.com" in url_base:
        return f"{url_base}/commit/{sha}"
    elif "gitlab.com" in url_base:
        return f"{url_base}/-/commit/{sha}"
    elif "bitbucket.org" in url_base:
        return f"{url_base}/commits/{sha}"
    else:
        # Generic: assume GitHub-style URL
        return f"{url_base}/commit/{sha}"


def bootstrap_commits(count: int = 100) -> list[Commit]:
    """Get the last N commits for initial bootstrap.

    This is used when no state exists yet — it loads the last N commits
    into the store without enriching them (enrichment happens separately).

    Args:
        count: Number of commits to load (default: 100).

    Returns:
        List of Commit objects in chronological order (oldest first).
    """
    return new_commits_since(None, max_commits=count)
