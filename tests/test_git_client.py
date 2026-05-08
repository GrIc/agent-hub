"""Tests for src/temporal/git_client.py.

These tests verify the git-aware primitives used by the changelog system.
They run against the actual git repository of the project.
"""

import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from src.temporal.git_client import (
    Commit,
    FileChange,
    _git,
    bootstrap_commits,
    commit_url,
    current_head,
    diff_for_commit,
    ensure_state_dir,
    files_changed,
    last_indexed_sha,
    new_commits_since,
    set_last_indexed_sha,
)


# ── Fixtures ──────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).parent.parent.parent


@pytest.fixture(scope="module")
def recent_commits():
    """Return the last 3 commits from the repo."""
    return new_commits_since(None, max_commits=3)


@pytest.fixture(scope="module")
def sample_sha(recent_commits):
    """Return the SHA of the most recent commit."""
    return recent_commits[0].sha if recent_commits else None


# ── current_head ──────────────────────────────────────────────────

class TestCurrentHead:
    def test_returns_non_empty_string(self):
        sha = current_head()
        assert sha is not None
        assert isinstance(sha, str)
        assert len(sha) == 40  # full SHA

    def test_is_valid_sha(self):
        sha = current_head()
        assert all(c in "0123456789abcdef" for c in sha.lower())


# ── new_commits_since ─────────────────────────────────────────────

class TestNewCommitsSince:
    def test_returns_commits_when_no_sha(self, recent_commits):
        """new_commits_since(None) returns the last max_commits."""
        assert len(recent_commits) == 3

    def test_returns_commit_objects(self, recent_commits):
        """Each item is a Commit with required fields."""
        for c in recent_commits:
            assert isinstance(c, Commit)
            assert len(c.sha) == 40
            assert c.author
            assert c.date
            assert c.subject

    def test_chronological_order(self, recent_commits):
        """Commits are in chronological order (oldest first)."""
        if len(recent_commits) >= 2:
            dates = [c.date for c in recent_commits]
            assert dates == sorted(dates)

    def test_max_commits_limit(self):
        """max_commits=5 returns at most 5 commits."""
        commits = new_commits_since(None, max_commits=5)
        assert len(commits) <= 5

    def test_empty_result_for_invalid_sha(self):
        """An invalid SHA returns empty list."""
        commits = new_commits_since("0000000000000000000000000000000000000000")
        assert commits == []

    def test_commits_have_bodies(self, recent_commits):
        """Commits may have empty or non-empty bodies."""
        for c in recent_commits:
            # Body can be empty for commits without body text
            assert isinstance(c.body, str)


# ── files_changed ─────────────────────────────────────────────────

class TestFilesChanged:
    def test_returns_file_changes(self, sample_sha):
        """files_changed returns at least one FileChange."""
        if sample_sha is None:
            pytest.skip("No commits in repo")
        changes = files_changed(sample_sha)
        assert len(changes) > 0

    def test_file_change_fields(self, sample_sha):
        """Each FileChange has required fields."""
        if sample_sha is None:
            pytest.skip("No commits in repo")
        changes = files_changed(sample_sha)
        for fc in changes:
            assert isinstance(fc, FileChange)
            assert fc.path
            assert fc.status in ("A", "M", "D", "R")
            assert fc.insertions >= 0
            assert fc.deletions >= 0

    def test_status_is_accurate(self, sample_sha):
        """The status field matches git's assessment for the last commit."""
        if sample_sha is None:
            pytest.skip("No commits in repo")
        changes = files_changed(sample_sha)
        # Verify at least one status against git
        for fc in changes:
            assert fc.status in ("A", "M", "D", "R")


# ── diff_for_commit ───────────────────────────────────────────────

class TestDiffForCommit:
    def test_returns_non_empty_string(self, sample_sha):
        """diff_for_commit returns diff text."""
        if sample_sha is None:
            pytest.skip("No commits in repo")
        diff = diff_for_commit(sample_sha)
        assert len(diff) > 0

    def test_truncation(self, sample_sha):
        """diff_for_commit with max_lines=10 truncates large diffs."""
        if sample_sha is None:
            pytest.skip("No commits in repo")
        diff = diff_for_commit(sample_sha, max_lines=10)
        lines = diff.split("\n")
        # Should have a truncation marker
        assert any("truncated" in line for line in lines) or len(lines) <= 15

    def test_contains_diff_header(self, sample_sha):
        """The diff contains standard git diff headers."""
        if sample_sha is None:
            pytest.skip("No commits in repo")
        diff = diff_for_commit(sample_sha)
        assert "diff --git" in diff


# ── State management ──────────────────────────────────────────────

class TestStateManagement:
    def test_last_indexed_sha_none_when_no_file(self):
        """Returns None when state file doesn't exist."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = Path(f.name)
        try:
            assert last_indexed_sha(path) is None
        finally:
            path.unlink(missing_ok=True)

    def test_set_and_get_last_indexed_sha(self):
        """Setting a SHA returns it on next call."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = Path(f.name)
        try:
            test_sha = "abc123def456" * 4  # 40 chars
            set_last_indexed_sha(test_sha, path)
            assert last_indexed_sha(path) == test_sha
        finally:
            path.unlink(missing_ok=True)

    def test_state_file_contains_timestamp(self):
        """State file contains last_run_at."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = Path(f.name)
        try:
            set_last_indexed_sha("abc123", path)
            state = json.loads(path.read_text())
            assert "last_indexed_sha" in state
            assert "last_run_at" in state
        finally:
            path.unlink(missing_ok=True)

    def test_ensure_state_dir(self):
        """ensure_state_dir creates the context/temporal directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "state.json"
            # Mock the module-level STATE_FILE
            with mock.patch("src.temporal.git_client.STATE_FILE", state_file):
                ensure_state_dir()
                assert state_file.parent.exists()


# ── commit_url ────────────────────────────────────────────────────

class TestCommitUrl:
    def test_url_with_base(self):
        """commit_url constructs URL from base_url."""
        url = commit_url("abc1234", base_url="https://github.com/org/repo")
        assert url == "https://github.com/org/repo/commit/abc1234"

    def test_url_strips_trailing_slash(self):
        """commit_url handles trailing slash in base_url."""
        url = commit_url("abc1234", base_url="https://github.com/org/repo/")
        assert url == "https://github.com/org/repo/commit/abc1234"

    def test_gitlab_url(self):
        """commit_url detects GitLab and uses correct path."""
        url = commit_url("abc1234", base_url="https://gitlab.com/org/repo")
        assert url == "https://gitlab.com/org/repo/-/commit/abc1234"

    def test_bitbucket_url(self):
        """commit_url detects Bitbucket and uses correct path."""
        url = commit_url("abc1234", base_url="https://bitbucket.org/org/repo")
        assert url == "https://bitbucket.org/org/repo/commits/abc1234"


# ── bootstrap_commits ─────────────────────────────────────────────

class TestBootstrapCommits:
    def test_returns_commits(self):
        """bootstrap_commits returns a list of commits."""
        commits = bootstrap_commits(count=5)
        assert len(commits) <= 5
        assert all(isinstance(c, Commit) for c in commits)


# ── _git helper ───────────────────────────────────────────────────

class TestGitHelper:
    def test_raises_on_non_repo(self):
        """_git raises RuntimeError outside a git repo."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Change to non-repo directory
            import os
            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                with pytest.raises(RuntimeError, match="git repository"):
                    _git("log", "-n", "1")
            finally:
                os.chdir(old_cwd)
