"""SQLite store for enriched commits.

Schema:
    commits(
        sha PK,
        author,
        date,
        subject,
        body,
        files_json,           -- JSON array of FileChange dicts
        intent,               -- feature|fix|refactor|chore|docs|test|unknown
        summary,              -- 1-2 sentence narrative
        modules_affected_json,-- JSON array of module path strings
        risk_score,           -- float in [0, 1]
        enriched_at,          -- ISO 8601 timestamp (NULL if not yet enriched)
        g_version             -- grounding version string
    )

The 'enriched' fields (intent, summary, modules_affected, risk_score, enriched_at,
g_version) are populated by src/temporal/enricher.py. Before enrichment, they are
NULL/empty.

Usage:
    store = TemporalStore("context/temporal/commits.sqlite")
    store.upsert_commit(commit, files)
    store.set_enrichment(sha, intent="fix", summary="...", ...)
    commits = store.commits_in_range(since, until)
"""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.temporal.git_client import Commit, FileChange

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("context/temporal/commits.sqlite")


class TemporalStore:
    """SQLite-backed store for git commit metadata and enrichment results."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        """Initialize the temporal store.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._connect()
        self._ensure_schema()

    def _connect(self) -> None:
        """Open a connection to the SQLite database."""
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

    def _ensure_schema(self) -> None:
        """Create the commits table if it doesn't exist."""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS commits (
                sha                     TEXT PRIMARY KEY,
                author                  TEXT NOT NULL DEFAULT '',
                date                    TEXT NOT NULL DEFAULT '',
                subject                 TEXT NOT NULL DEFAULT '',
                body                    TEXT NOT NULL DEFAULT '',
                files_json              TEXT NOT NULL DEFAULT '[]',
                intent                  TEXT DEFAULT NULL,
                summary                 TEXT DEFAULT NULL,
                modules_affected_json   TEXT DEFAULT NULL,
                risk_score              REAL DEFAULT 0.0,
                enriched_at             TEXT DEFAULT NULL,
                g_version               TEXT DEFAULT NULL
            )
        """)
        self._conn.commit()

    @property
    def connection(self) -> sqlite3.Connection:
        """Return the current database connection, reconnecting if needed."""
        if self._conn is None:
            self._connect()
        try:
            self._conn.execute("SELECT 1")
        except sqlite3.ProgrammingError:
            self._connect()
        return self._conn

    # ── Upsert ────────────────────────────────────────────────────

    def upsert_commit(self, commit: Commit, files: List[FileChange]) -> None:
        """Insert or update a commit record.

        This is idempotent: calling it twice with the same data has no additional effect.

        Args:
            commit: The Commit object to store.
            files: List of FileChange objects for this commit.
        """
        files_json = json.dumps([
            {"path": f.path, "status": f.status, "insertions": f.insertions, "deletions": f.deletions}
            for f in files
        ], ensure_ascii=False)

        self.connection.execute("""
            INSERT INTO commits (sha, author, date, subject, body, files_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(sha) DO UPDATE SET
                author = excluded.author,
                date = excluded.date,
                subject = excluded.subject,
                body = excluded.body,
                files_json = excluded.files_json
        """, (
            commit.sha,
            commit.author,
            commit.date,
            commit.subject,
            commit.body,
            files_json,
        ))
        self.connection.commit()

    # ── Enrichment ────────────────────────────────────────────────

    def is_enriched(self, sha: str) -> bool:
        """Check if a commit has been enriched (intent/summary populated).

        Args:
            sha: The commit SHA.

        Returns:
            True if the commit has enrichment data, False otherwise.
        """
        row = self.connection.execute(
            "SELECT enriched_at FROM commits WHERE sha = ?", (sha,)
        ).fetchone()
        return row is not None and row["enriched_at"] is not None

    def set_enrichment(
        self,
        sha: str,
        *,
        intent: str,
        summary: str,
        modules_affected: List[str],
        risk_score: float,
        g_version: str,
    ) -> None:
        """Set enrichment data for a commit.

        Args:
            sha: The commit SHA.
            intent: One of feature, fix, refactor, chore, docs, test, unknown.
            summary: 1-2 sentence narrative.
            modules_affected: List of module path strings.
            risk_score: Float in [0, 1].
            g_version: Grounding version string.
        """
        modules_json = json.dumps(modules_affected, ensure_ascii=False)

        from datetime import datetime, timezone
        enriched_at = datetime.now(timezone.utc).isoformat()

        self.connection.execute("""
            UPDATE commits SET
                intent = ?,
                summary = ?,
                modules_affected_json = ?,
                risk_score = ?,
                enriched_at = ?,
                g_version = ?
            WHERE sha = ?
        """, (
            intent,
            summary,
            modules_json,
            risk_score,
            enriched_at,
            g_version,
            sha,
        ))
        self.connection.commit()

    def get_commit(self, sha: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single commit record.

        Args:
            sha: The commit SHA.

        Returns:
            Dict with commit fields, or None if not found.
        """
        row = self.connection.execute(
            "SELECT * FROM commits WHERE sha = ?", (sha,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """Convert a sqlite3.Row to a dict, parsing JSON fields."""
        d = dict(row)
        # Parse JSON fields
        if d.get("files_json"):
            try:
                d["files"] = json.loads(d["files_json"])
            except (json.JSONDecodeError, TypeError):
                d["files"] = []
        else:
            d["files"] = []

        if d.get("modules_affected_json"):
            try:
                d["modules_affected"] = json.loads(d["modules_affected_json"])
            except (json.JSONDecodeError, TypeError):
                d["modules_affected"] = []
        else:
            d["modules_affected"] = []

        return d

    # ── Queries ───────────────────────────────────────────────────

    def commits_in_range(self, since: str, until: str) -> List[Dict[str, Any]]:
        """Get commits between two SHAs (inclusive).

        Args:
            since: Starting SHA (inclusive).
            until: Ending SHA (inclusive).

        Returns:
            List of commit dicts, ordered chronologically (oldest first).
        """
        cursor = self.connection.execute("""
            SELECT * FROM commits
            WHERE sha >= ? AND sha <= ?
            ORDER BY date ASC
        """, (since, until))
        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def commits_for_module(self, module: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent commits that affected a specific module.

        Args:
            module: Module path prefix (e.g. "src/auth").
            limit: Maximum number of commits to return.

        Returns:
            List of commit dicts, ordered by date (newest first).
        """
        cursor = self.connection.execute("""
            SELECT * FROM commits
            WHERE modules_affected_json LIKE ?
            ORDER BY date DESC
            LIMIT ?
        """, (f'%"{module}"%', limit))
        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def all_unenriched(self, limit: int = 1000) -> List[str]:
        """Get SHAs of commits that haven't been enriched yet.

        Args:
            limit: Maximum number of SHAs to return.

        Returns:
            List of commit SHAs.
        """
        cursor = self.connection.execute("""
            SELECT sha FROM commits
            WHERE enriched_at IS NULL
            ORDER BY date ASC
            LIMIT ?
        """, (limit,))
        return [row["sha"] for row in cursor.fetchall()]

    def enriched_commits(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recently enriched commits.

        Args:
            limit: Maximum number of commits to return.

        Returns:
            List of commit dicts, ordered by enrichment date (newest first).
        """
        cursor = self.connection.execute("""
            SELECT * FROM commits
            WHERE enriched_at IS NOT NULL
            ORDER BY enriched_at DESC
            LIMIT ?
        """, (limit,))
        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def commits_by_intent(self, intent: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get commits filtered by intent.

        Args:
            intent: One of feature, fix, refactor, chore, docs, test, unknown.
            limit: Maximum number of commits to return.

        Returns:
            List of commit dicts.
        """
        cursor = self.connection.execute("""
            SELECT * FROM commits
            WHERE intent = ?
            ORDER BY date DESC
            LIMIT ?
        """, (intent, limit))
        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def commit_count(self) -> int:
        """Return total number of commits in the store."""
        row = self.connection.execute("SELECT COUNT(*) as cnt FROM commits").fetchone()
        return row["cnt"] if row else 0

    def enriched_count(self) -> int:
        """Return number of enriched commits."""
        row = self.connection.execute(
            "SELECT COUNT(*) as cnt FROM commits WHERE enriched_at IS NOT NULL"
        ).fetchone()
        return row["cnt"] if row else 0

    # ── Maintenance ───────────────────────────────────────────────

    def delete_commits_before(self, sha: str) -> int:
        """Delete all commits before the given SHA.

        Args:
            sha: Delete commits older than this SHA.

        Returns:
            Number of commits deleted.
        """
        cursor = self.connection.execute(
            "DELETE FROM commits WHERE sha < ?", (sha,)
        )
        self.connection.commit()
        return cursor.rowcount

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "TemporalStore":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()

    def __del__(self) -> None:
        """Destructor: ensure connection is closed."""
        self.close()
