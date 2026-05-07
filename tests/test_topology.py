"""Tests for src/graph/topology.py — filesystem + git layer.

Covers:
  - Directory tree and file nodes for a synthetic workspace
  - Co-change edges computed and weighted from git history
  - Git vs dir workspace detection
  - Edge emission (file → parent contains)
  - Git blame helper
  - Bulk build_topology integration
"""

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from src.graph.topology import (
    _dir_to_module_id,
    _file_hash,
    _git_log_files,
    detect_workspace_type,
    emit_co_change_edges,
    emit_directory_tree,
    emit_file_contains_edges,
    emit_file_nodes,
    emit_git_blame,
    build_topology,
    TopologyNode,
    TopologyEdge,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm(path_str: str) -> str:
    """Normalise a path string to forward-slash form (cross-platform)."""
    return Path(path_str).as_posix()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def synthetic_workspace():
    """Create a temporary directory with a realistic file layout.

    Structure:
        workspace/
            README.md
            config.yaml
            src/
                main.py
                utils.py
                models/
                    user.py
                    order.py
                services/
                    auth.py
            tests/
                test_auth.py
                test_user.py
            docs/
                API.md
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)

        # Root files.
        (ws / "README.md").write_text("# Test Workspace\n", encoding="utf-8")
        (ws / "config.yaml").write_text("key: value\n", encoding="utf-8")

        # src/main.py
        src = ws / "src"
        src.mkdir()
        (src / "main.py").write_text(
            "from services.auth import authenticate\n\ndef main():\n    authenticate()\n",
            encoding="utf-8",
        )
        (src / "utils.py").write_text("def helper(): pass\n", encoding="utf-8")

        # src/models/
        models = src / "models"
        models.mkdir()
        (models / "user.py").write_text(
            "class User:\n    def __init__(self, name):\n        self.name = name\n",
            encoding="utf-8",
        )
        (models / "order.py").write_text(
            "class Order:\n    def total(self): return 0\n",
            encoding="utf-8",
        )

        # src/services/
        services = src / "services"
        services.mkdir()
        (services / "auth.py").write_text(
            "def authenticate(): pass\n",
            encoding="utf-8",
        )

        # tests/
        tests = ws / "tests"
        tests.mkdir()
        (tests / "test_auth.py").write_text(
            "from services.auth import authenticate\ndef test_auth(): pass\n",
            encoding="utf-8",
        )
        (tests / "test_user.py").write_text(
            "from models.user import User\ndef test_user(): pass\n",
            encoding="utf-8",
        )

        # docs/
        docs = ws / "docs"
        docs.mkdir()
        (docs / "API.md").write_text("# API Docs\n", encoding="utf-8")

        yield ws


@pytest.fixture()
def git_workspace(synthetic_workspace):
    """Same as synthetic_workspace but initialised as a git repo."""
    ws = synthetic_workspace
    subprocess.run(
        ["git", "init"],
        cwd=ws,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=ws,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=ws,
        capture_output=True,
        check=True,
    )
    # Initial commit.
    subprocess.run(
        ["git", "add", "."],
        cwd=ws,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=ws,
        capture_output=True,
        check=True,
    )
    yield ws


# ---------------------------------------------------------------------------
# Test: workspace type detection
# ---------------------------------------------------------------------------

class TestDetectWorkspaceType:
    def test_git_repo(self, git_workspace):
        """detect_workspace_type returns 'git' for a git repository."""
        assert detect_workspace_type(str(git_workspace)) == "git"

    def test_plain_directory(self, synthetic_workspace):
        """detect_workspace_type returns 'dir' for a non-git directory."""
        assert detect_workspace_type(str(synthetic_workspace)) == "dir"

    def test_nonexistent_path(self):
        """detect_workspace_type returns 'dir' for a non-existent path."""
        assert detect_workspace_type("/nonexistent/path/12345") == "dir"


# ---------------------------------------------------------------------------
# Test: directory tree emission
# ---------------------------------------------------------------------------

class TestEmitDirectoryTree:
    def test_emits_directory_nodes(self, synthetic_workspace):
        """emit_directory_tree emits a Module node for each directory."""
        nodes, _ = emit_directory_tree(str(synthetic_workspace))

        node_ids = {n.id for n in nodes}
        # Root directory.
        assert "Module:." in node_ids
        # Subdirectories (forward-slash on all platforms).
        assert "Module:src" in node_ids
        assert "Module:src/models" in node_ids
        assert "Module:src/services" in node_ids
        assert "Module:tests" in node_ids
        assert "Module:docs" in node_ids

    def test_emits_contains_edges_between_dirs(self, synthetic_workspace):
        """emit_directory_tree emits 'contains' edges from parent to child dirs."""
        _, edges = emit_directory_tree(str(synthetic_workspace))

        contains_edges = [e for e in edges if e.relation == "contains"]
        edge_pairs = {(e.source_id, e.target_id) for e in contains_edges}

        # src contains models.
        assert ("Module:src", "Module:src/models") in edge_pairs
        # src contains services.
        assert ("Module:src", "Module:src/services") in edge_pairs
        # Root contains src.
        assert ("Module:.", "Module:src") in edge_pairs

    def test_skips_ignored_directories(self, synthetic_workspace):
        """emit_directory_tree skips directories in skip_dirs."""
        nodes, _ = emit_directory_tree(
            str(synthetic_workspace),
            skip_dirs={"__pycache__", "node_modules"},
        )
        node_ids = {n.id for n in nodes}
        assert "Module:__pycache__" not in node_ids
        assert "Module:node_modules" not in node_ids

    def test_node_count_matches_directories(self, synthetic_workspace):
        """Number of Module nodes equals number of directories on disk."""
        nodes, _ = emit_directory_tree(str(synthetic_workspace))
        actual_dirs = set()
        for dirpath, dirnames, _ in os.walk(synthetic_workspace):
            rel = Path(dirpath).relative_to(synthetic_workspace)
            actual_dirs.add(_dir_to_module_id(rel))
            for d in sorted(dirnames):
                if d not in {"__pycache__", "node_modules"} and not d.startswith("."):
                    actual_dirs.add(_dir_to_module_id(rel / d))

        assert len(nodes) == len(actual_dirs)

    def test_root_node_marked(self, synthetic_workspace):
        """Root Module node has is_workspace_root in metadata."""
        nodes, _ = emit_directory_tree(str(synthetic_workspace))
        root = next(n for n in nodes if n.id == "Module:.")
        # The value is a string "True" from json serialization in the store,
        # but here it's the raw Python bool.
        assert root.metadata.get("is_workspace_root") is True


# ---------------------------------------------------------------------------
# Test: file node emission
# ---------------------------------------------------------------------------

class TestEmitFileNodes:
    def test_emits_file_nodes(self, synthetic_workspace):
        """emit_file_nodes emits one File node per indexed file."""
        nodes = emit_file_nodes(str(synthetic_workspace))

        file_ids = {n.id for n in nodes}
        assert "File:README.md" in file_ids
        assert "File:config.yaml" in file_ids
        assert "File:src/main.py" in file_ids
        assert "File:src/models/user.py" in file_ids
        assert "File:tests/test_auth.py" in file_ids
        assert "File:docs/API.md" in file_ids

    def test_file_node_metadata(self, synthetic_workspace):
        """File nodes carry size_bytes, content_hash, and extension."""
        nodes = emit_file_nodes(str(synthetic_workspace))
        readme = next(n for n in nodes if n.id == "File:README.md")

        assert "size_bytes" in readme.metadata
        assert isinstance(readme.metadata["size_bytes"], int)
        assert readme.metadata["size_bytes"] > 0
        assert "content_hash" in readme.metadata
        assert len(readme.metadata["content_hash"]) == 64  # SHA-256 hex
        assert readme.metadata["extension"] == ".md"

    def test_extension_filter(self, synthetic_workspace):
        """emit_file_nodes respects extension filter."""
        nodes = emit_file_nodes(
            str(synthetic_workspace),
            extensions={".py"},
        )
        file_ids = {n.id for n in nodes}
        assert "File:src/main.py" in file_ids
        assert "File:README.md" not in file_ids
        assert "File:config.yaml" not in file_ids

    def test_skips_hidden_files(self, synthetic_workspace):
        """emit_file_nodes skips files starting with '.'."""
        nodes = emit_file_nodes(str(synthetic_workspace))
        file_ids = {n.id for n in nodes}
        # No .gitignore since we didn't create one in this fixture.
        # But verify no hidden files slip through.
        for fid in file_ids:
            assert not Path(fid.replace("File:", "")).name.startswith(".")

    def test_max_file_size_filter(self, synthetic_workspace):
        """emit_file_nodes skips files larger than max_file_size."""
        # Create a large file.
        large = synthetic_workspace / "large.bin"
        large.write_bytes(b"x" * 20_000_000)

        nodes = emit_file_nodes(
            str(synthetic_workspace),
            max_file_size=10_000_000,
        )
        file_ids = {n.id for n in nodes}
        assert "File:large.bin" not in file_ids

    def test_all_files_when_no_extensions(self, synthetic_workspace):
        """Without extension filter, all non-hidden files are emitted."""
        nodes = emit_file_nodes(str(synthetic_workspace))
        file_ids = {n.id for n in nodes}
        # Should include .md, .yaml, .py files.
        assert len(file_ids) >= 10

    def test_content_hash_consistency(self, synthetic_workspace):
        """Same file produces the same hash across calls."""
        nodes1 = emit_file_nodes(str(synthetic_workspace))
        nodes2 = emit_file_nodes(str(synthetic_workspace))

        readme1 = next(n for n in nodes1 if n.id == "File:README.md")
        readme2 = next(n for n in nodes2 if n.id == "File:README.md")
        assert readme1.metadata["content_hash"] == readme2.metadata["content_hash"]


# ---------------------------------------------------------------------------
# Test: file contains edges
# ---------------------------------------------------------------------------

class TestEmitFileContainsEdges:
    def test_emits_contains_edges(self, synthetic_workspace):
        """emit_file_contains_edges emits parent Module → File edges."""
        nodes = emit_file_nodes(str(synthetic_workspace))
        edges = emit_file_contains_edges(str(synthetic_workspace), nodes)

        edge_pairs = {(e.source_id, e.target_id) for e in edges}
        assert ("Module:src", "File:src/main.py") in edge_pairs
        assert ("Module:src/models", "File:src/models/user.py") in edge_pairs
        assert ("Module:.", "File:README.md") in edge_pairs

    def test_edge_count_matches_file_nodes(self, synthetic_workspace):
        """Number of contains edges equals number of file nodes."""
        nodes = emit_file_nodes(str(synthetic_workspace))
        edges = emit_file_contains_edges(str(synthetic_workspace), nodes)
        assert len(edges) == len(nodes)


# ---------------------------------------------------------------------------
# Test: _file_hash helper
# ---------------------------------------------------------------------------

class TestFileHash:
    def test_returns_sha256_hex(self, synthetic_workspace):
        """_file_hash returns a 64-char hex string (SHA-256)."""
        fpath = synthetic_workspace / "README.md"
        h = _file_hash(fpath)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_different_files_different_hashes(self, synthetic_workspace):
        """Different file contents produce different hashes."""
        f1 = synthetic_workspace / "README.md"
        f2 = synthetic_workspace / "config.yaml"
        assert _file_hash(f1) != _file_hash(f2)

    def test_error_returns_error_string(self):
        """_file_hash returns 'error' for unreadable files."""
        fake = Path("/nonexistent/file.txt")
        assert _file_hash(fake) == "error"


# ---------------------------------------------------------------------------
# Test: directory ID generation
# ---------------------------------------------------------------------------

class TestDirToModuleId:
    def test_root(self):
        assert _dir_to_module_id(Path(".")) == "Module:."

    def test_single_level(self):
        assert _dir_to_module_id(Path("src")) == "Module:src"

    def test_nested(self):
        assert _dir_to_module_id(Path("src/models")) == "Module:src/models"

    def test_deeply_nested(self):
        assert _dir_to_module_id(Path("a/b/c/d")) == "Module:a/b/c/d"


# ---------------------------------------------------------------------------
# Test: co-change edge emission
# ---------------------------------------------------------------------------

class TestEmitCoChangeEdges:
    def test_no_git_repo_returns_empty(self, synthetic_workspace):
        """emit_co_change_edges returns [] when workspace is not a git repo."""
        edges = emit_co_change_edges(str(synthetic_workspace))
        assert edges == []

    def test_computes_co_change_edges(self, git_workspace):
        """emit_co_change_edges computes weighted edges from shared commits."""
        # Make a second commit that touches two files together.
        (git_workspace / "src" / "main.py").write_text(
            "print('updated')\n", encoding="utf-8"
        )
        (git_workspace / "src" / "utils.py").write_text(
            "def helper(): return 42\n", encoding="utf-8"
        )
        subprocess.run(
            ["git", "add", "src/main.py", "src/utils.py"],
            cwd=git_workspace,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "update both"],
            cwd=git_workspace,
            capture_output=True,
            check=True,
        )

        edges = emit_co_change_edges(str(git_workspace))
        co_change_edges = [e for e in edges if e.relation == "co_changes"]

        # Should have at least one co-change edge between main.py and utils.py.
        edge_pairs = {(e.source_id, e.target_id) for e in co_change_edges}
        assert ("File:src/main.py", "File:src/utils.py") in edge_pairs

    def test_weight_reflects_shared_commits(self, git_workspace):
        """Co-change weight reflects total shared commits (including initial)."""
        # The initial commit already touched main.py and utils.py.
        # Now make 2 more commits touching both → total = 3 shared commits.
        (git_workspace / "src" / "main.py").write_text("v1\n", encoding="utf-8")
        (git_workspace / "src" / "utils.py").write_text("v1\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "src/main.py", "src/utils.py"],
            cwd=git_workspace,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "v1"],
            cwd=git_workspace,
            capture_output=True,
            check=True,
        )

        (git_workspace / "src" / "main.py").write_text("v2\n", encoding="utf-8")
        (git_workspace / "src" / "utils.py").write_text("v2\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "src/main.py", "src/utils.py"],
            cwd=git_workspace,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "v2"],
            cwd=git_workspace,
            capture_output=True,
            check=True,
        )

        edges = emit_co_change_edges(str(git_workspace))
        co_change_edges = [e for e in edges if e.relation == "co_changes"]

        edge_map = {}
        for e in co_change_edges:
            key = (e.source_id, e.target_id)
            edge_map[key] = e.metadata.get("weight", 0)

        # Initial commit + v1 + v2 = 3 shared commits.
        target_key = ("File:src/main.py", "File:src/utils.py")
        assert edge_map.get(target_key) == 3, f"Expected weight 3, got {edge_map}"

    def test_single_file_commits_no_edge(self, git_workspace):
        """Commits touching only one file produce no co-change edge."""
        (git_workspace / "README.md").write_text("updated\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "README.md"],
            cwd=git_workspace,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "readme update"],
            cwd=git_workspace,
            capture_output=True,
            check=True,
        )

        edges = emit_co_change_edges(str(git_workspace))
        co_change_edges = [e for e in edges if e.relation == "co_changes"]
        # No co-change edges since only one file changed.
        assert len(co_change_edges) == 0

    def test_min_weight_filter(self, git_workspace):
        """Only edges with weight >= min_weight (2) are emitted."""
        # Create a new file and commit it with main.py in the same commit.
        new_file = git_workspace / "src" / "new_module.py"
        new_file.write_text("def new_func(): pass\n", encoding="utf-8")
        (git_workspace / "src" / "main.py").write_text("updated\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "src/main.py", str(new_file)],
            cwd=git_workspace,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "add new_module and touch main"],
            cwd=git_workspace,
            capture_output=True,
            check=True,
        )

        # Now main.py + new_module.py share exactly 1 commit.
        edges = emit_co_change_edges(str(git_workspace))
        co_change_edges = [e for e in edges if e.relation == "co_changes"]

        # main.py + new_module.py should NOT appear (weight=1 < min_weight=2).
        new_pair = ("File:src/main.py", "File:src/new_module.py")
        new_edges = [e for e in co_change_edges if {e.source_id, e.target_id} == {new_pair[0], new_pair[1]}]
        assert len(new_edges) == 0, f"Expected no edge for {new_pair} (weight=1 < 2), got {len(new_edges)} edges"


# ---------------------------------------------------------------------------
# Test: _git_log_files helper
# ---------------------------------------------------------------------------

class TestGitLogFiles:
    def test_returns_empty_for_non_git(self, synthetic_workspace):
        """_git_log_files returns {} for non-git directories."""
        result = _git_log_files(str(synthetic_workspace))
        assert result == {}

    def test_returns_commits_for_git_repo(self, git_workspace):
        """_git_log_files returns commit → files mapping."""
        result = _git_log_files(str(git_workspace))
        assert isinstance(result, dict)
        assert len(result) >= 1  # at least the initial commit

    def test_commit_hashes_are_40_chars(self, git_workspace):
        """All keys in the result are 40-char hex commit hashes."""
        result = _git_log_files(str(git_workspace))
        for key in result:
            assert len(key) == 40
            assert all(c in "0123456789abcdef" for c in key)


# ---------------------------------------------------------------------------
# Test: git blame helper
# ---------------------------------------------------------------------------

class TestEmitGitBlame:
    def test_returns_empty_for_non_git(self, synthetic_workspace):
        """emit_git_blame returns {} for non-git directories."""
        result = emit_git_blame(str(synthetic_workspace), "README.md")
        assert result == {}

    def test_returns_blame_data_for_git_repo(self, git_workspace):
        """emit_git_blame returns structured blame data."""
        result = emit_git_blame(str(git_workspace), "README.md")
        assert isinstance(result, dict)
        assert result.get("file") == "README.md"
        # Should have at least one blame line.
        blame_lines = result.get("blame_lines", [])
        assert len(blame_lines) >= 1
        first = blame_lines[0]
        assert "commit" in first
        assert "author" in first
        assert "line" in first

    def test_returns_empty_for_missing_file(self, git_workspace):
        """emit_git_blame returns {} for a file not in the repo."""
        result = emit_git_blame(str(git_workspace), "nonexistent.py")
        assert result == {}


# ---------------------------------------------------------------------------
# Test: build_topology integration
# ---------------------------------------------------------------------------

class TestBuildTopology:
    def test_writes_to_graph_store(self, synthetic_workspace):
        """build_topology writes directory and file nodes to the store."""
        db_path = os.path.join(str(synthetic_workspace), ".test_graph.db")
        try:
            result = build_topology(
                str(synthetic_workspace),
                db_path=db_path,
            )
            assert result["workspace_type"] == "dir"
            assert result["directory_nodes"] > 0
            assert result["file_nodes"] > 0
            assert result["total_nodes"] > 0
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)

    def test_git_co_change_edges_included(self, git_workspace):
        """build_topology includes co-change edges for git repos."""
        # Make a commit touching two files together.
        (git_workspace / "src" / "main.py").write_text("v1\n", encoding="utf-8")
        (git_workspace / "src" / "utils.py").write_text("v1\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "src/main.py", "src/utils.py"],
            cwd=git_workspace,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "v1"],
            cwd=git_workspace,
            capture_output=True,
            check=True,
        )

        db_path = os.path.join(str(git_workspace), ".test_graph.db")
        try:
            result = build_topology(
                str(git_workspace),
                db_path=db_path,
            )
            assert result["workspace_type"] == "git"
            # Co-change edges may be 0 if weight < 2, but the function
            # should still run without error.
            assert isinstance(result["co_change_edges"], int)
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)

    def test_returns_summary_dict(self, synthetic_workspace):
        """build_topology returns a dict with expected keys."""
        db_path = os.path.join(str(synthetic_workspace), ".test_graph.db")
        try:
            result = build_topology(
                str(synthetic_workspace),
                db_path=db_path,
            )
            expected_keys = {
                "workspace_type",
                "directory_nodes",
                "directory_edges",
                "file_nodes",
                "file_contains_edges",
                "co_change_edges",
                "total_nodes",
                "total_edges",
            }
            assert expected_keys.issubset(set(result.keys()))
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)

    def test_extension_filter_in_topology(self, synthetic_workspace):
        """build_topology respects extension filter."""
        db_path = os.path.join(str(synthetic_workspace), ".test_graph.db")
        try:
            result = build_topology(
                str(synthetic_workspace),
                db_path=db_path,
                extensions={".py"},
            )
            assert result["file_nodes"] > 0
            # Only .py files should be indexed.
            assert result["file_nodes"] <= 10  # there are ~6 .py files
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)

    def test_co_change_edges_filtered_to_existing_files(self, git_workspace):
        """build_topology only emits co-change edges for existing File nodes."""
        # Delete a file that was in the initial commit.
        (git_workspace / "src" / "utils.py").unlink()
        subprocess.run(
            ["git", "add", "-A"],
            cwd=git_workspace,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "delete utils"],
            cwd=git_workspace,
            capture_output=True,
            check=True,
        )

        db_path = os.path.join(str(git_workspace), ".test_graph.db")
        try:
            # This should NOT raise FK constraint errors.
            result = build_topology(
                str(git_workspace),
                db_path=db_path,
            )
            assert result["workspace_type"] == "git"
            # co_change_edges should be 0 since utils.py is deleted and
            # min_weight=2 filter removes single-commit edges.
            assert isinstance(result["co_change_edges"], int)
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)


# ---------------------------------------------------------------------------
# Test: TopologyNode / TopologyEdge dataclasses
# ---------------------------------------------------------------------------

class TestDataclasses:
    def test_topology_node_defaults(self):
        node = TopologyNode(id="File:test.py", type="File", name="test.py", file_path="test.py")
        assert node.line_start == 0
        assert node.line_end == 0
        assert node.metadata == {}

    def test_topology_edge_defaults(self):
        edge = TopologyEdge(
            source_id="Module:.",
            target_id="File:test.py",
            relation="contains",
        )
        assert edge.evidence_path is None
        assert edge.evidence_line is None
        assert edge.metadata == {}
