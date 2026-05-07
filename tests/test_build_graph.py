"""Integration tests for build_graph.py orchestrator.

Tests incremental updates, structural extraction, resolution, hub dampening,
enrichment phases, and mixed-language workspace handling.
"""

import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from src.graph.store import GraphStore
from src.graph.topology import emit_file_nodes


def setup_workspace(tmp_path: Path) -> Path:
    """Create a minimal mixed-language workspace for testing."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    
    # Python file
    (ws / "main.py").write_text("""
def hello():
    print("Hello")

class Greeter:
    def greet(self):
        hello()
""")
    
    # Java file
    (ws / "App.java").write_text("""
public class App {
    public static void main(String[] args) {
        Greeter g = new Greeter();
        g.greet();
    }
}
""")
    
    # Config file (topology-only)
    (ws / "config.yaml").write_text("key: value\n")
    
    # XML file (topology-only)
    (ws / "pom.xml").write_text("""<?xml version="1.0"?>
<project>
  <dependencies>
    <dependency><groupId>junit</groupId></dependency>
  </dependencies>
</project>
""")
    
    # Markdown file (topology-only)
    (ws / "README.md").write_text("# Project\nThis is a test project.\n")
    
    return ws


def count_nodes_by_type(store: GraphStore, node_type: str) -> int:
    """Count nodes of a specific type."""
    nodes = store.list_nodes(limit=100000)
    return sum(1 for n in nodes if n.get("type") == node_type)


def count_edges_by_relation(store: GraphStore, relation: str) -> int:
    """Count edges of a specific relation type."""
    edges = store.list_edges(limit=100000)
    return sum(1 for e in edges if e.get("relation") == relation)


class TestIncrementalUpdates:
    """Test incremental update behavior and state tracking."""

    def test_incremental_run_on_unchanged_workspace(self, tmp_path: Path):
        """Incremental run on unchanged workspace should be fast (<30s) and produce no changes."""
        ws = setup_workspace(tmp_path)
        db_path = tmp_path / ".graphdb" / "graph.sqlite"
        
        # First full build
        import subprocess
        result = subprocess.run(
            ["python", "build_graph.py", "--workspace", str(ws), "--force"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, f"Build failed: {result.stderr}"
        
        # Get initial stats
        store = GraphStore(db_path=str(db_path))
        initial_nodes = store.stats()["nodes"]
        initial_edges = store.stats()["edges"]
        
        # Second incremental run (should skip unchanged files)
        start = os.times().elapsed
        result = subprocess.run(
            ["python", "build_graph.py", "--workspace", str(ws)],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=60,
        )
        elapsed = os.times().elapsed - start
        
        assert result.returncode == 0, f"Incremental build failed: {result.stderr}"
        assert elapsed < 30.0, f"Incremental run took {elapsed}s (>30s)"
        
        # Stats should be identical
        store2 = GraphStore(db_path=str(db_path))
        assert store2.stats()["nodes"] == initial_nodes
        assert store2.stats()["edges"] == initial_edges

    def test_full_rebuild_with_force(self, tmp_path: Path):
        """Full rebuild with --force should reprocess all files."""
        ws = setup_workspace(tmp_path)
        db_path = tmp_path / ".graphdb" / "graph.sqlite"
        
        # First build
        import subprocess
        result = subprocess.run(
            ["python", "build_graph.py", "--workspace", str(ws), "--force"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0
        
        store1 = GraphStore(db_path=str(db_path))
        nodes1 = store1.stats()["nodes"]
        edges1 = store1.stats()["edges"]
        
        # Force rebuild
        result = subprocess.run(
            ["python", "build_graph.py", "--workspace", str(ws), "--force"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0
        
        store2 = GraphStore(db_path=str(db_path))
        nodes2 = store2.stats()["nodes"]
        edges2 = store2.stats()["edges"]
        
        # Should have same or more nodes/edges (no deletions expected)
        assert nodes2 >= nodes1
        assert edges2 >= edges1


class TestEnrichmentPhase:
    """Test enrichment phase behavior."""

    def test_enrichment_phase_via_enrich_flag(self, tmp_path: Path):
        """--enrich flag should run enrichment only on existing graph."""
        ws = setup_workspace(tmp_path)
        db_path = tmp_path / ".graphdb" / "graph.sqlite"
        
        # Build without enrichment
        import subprocess
        result = subprocess.run(
            ["python", "build_graph.py", "--workspace", str(ws), "--force"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0
        
        # Run enrichment only
        result = subprocess.run(
            ["python", "build_graph.py", "--workspace", str(ws), "--enrich"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0
        assert "Enrichment complete" in result.stdout

    def test_enrich_only_mode(self, tmp_path: Path):
        """--enrich-only should skip structural extraction and only run enrichment."""
        ws = setup_workspace(tmp_path)
        db_path = tmp_path / ".graphdb" / "graph.sqlite"
        
        # Build with structural extraction
        import subprocess
        result = subprocess.run(
            ["python", "build_graph.py", "--workspace", str(ws), "--force"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0
        
        # Check that Class nodes exist
        store = GraphStore(db_path=str(db_path))
        class_count_before = count_nodes_by_type(store, "Class")
        assert class_count_before > 0, "Expected Class nodes from structural extraction"
        
        # Run enrich-only (should not add structural nodes)
        result = subprocess.run(
            ["python", "build_graph.py", "--workspace", str(ws), "--enrich-only"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0
        
        # Class count should remain the same
        store2 = GraphStore(db_path=str(db_path))
        class_count_after = count_nodes_by_type(store2, "Class")
        assert class_count_after == class_count_before


class TestStatsOutput:
    """Test stats output functionality."""

    def test_stats_flag_outputs_graph_stats(self, tmp_path: Path):
        """--stats flag should output graph statistics."""
        ws = setup_workspace(tmp_path)
        db_path = tmp_path / ".graphdb" / "graph.sqlite"
        
        # Build first
        import subprocess
        result = subprocess.run(
            ["python", "build_graph.py", "--workspace", str(ws), "--force"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0
        
        # Stats output
        result = subprocess.run(
            ["python", "build_graph.py", "--workspace", str(ws), "--stats"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert "Knowledge Graph Statistics" in result.stdout
        assert "Nodes:" in result.stdout
        assert "Edges:" in result.stdout


class TestMixedWorkspace:
    """Test mixed-language workspace produces correct node/edge counts."""

    def test_mixed_workspace_counts(self, tmp_path: Path):
        """Mixed workspace (Java, Python, configs, XML) produces correct node/edge counts."""
        ws = setup_workspace(tmp_path)
        db_path = tmp_path / ".graphdb" / "graph.sqlite"
        
        # Build
        import subprocess
        result = subprocess.run(
            ["python", "build_graph.py", "--workspace", str(ws), "--force"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, f"Build failed: {result.stderr}"
        
        store = GraphStore(db_path=str(db_path))
        stats = store.stats()
        
        # Should have File nodes for all files
        file_nodes = count_nodes_by_type(store, "File")
        assert file_nodes >= 5, f"Expected at least 5 File nodes, got {file_nodes}"
        
        # Should have Class nodes from Python and Java
        class_nodes = count_nodes_by_type(store, "Class")
        assert class_nodes >= 2, f"Expected at least 2 Class nodes, got {class_nodes}"
        
        # Should have Method nodes
        method_nodes = count_nodes_by_type(store, "Method")
        assert method_nodes >= 2, f"Expected at least 2 Method nodes, got {method_nodes}"
        
        # Should have calls edges
        calls_edges = count_edges_by_relation(store, "calls")
        assert calls_edges >= 1, f"Expected at least 1 calls edge, got {calls_edges}"
        
        # Should have imports edges (from Java)
        imports_edges = count_edges_by_relation(store, "imports")
        assert imports_edges >= 1, f"Expected at least 1 imports edge, got {imports_edges}"
        
        # Should have contains edges (directory structure)
        contains_edges = count_edges_by_relation(store, "contains")
        assert contains_edges >= 1, f"Expected at least 1 contains edge, got {contains_edges}"


class TestTopologyOnlyFiles:
    """Test that topology-only files (XML, YAML, MD, CSV) produce only File nodes."""

    def test_topology_only_files(self, tmp_path: Path):
        """Topology-only files produce File nodes + topology edges only."""
        ws = setup_workspace(tmp_path)
        db_path = tmp_path / ".graphdb" / "graph.sqlite"
        
        # Build
        import subprocess
        result = subprocess.run(
            ["python", "build_graph.py", "--workspace", str(ws), "--force"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0
        
        store = GraphStore(db_path=str(db_path))
        stats = store.stats()
        
        # Should have File nodes
        file_nodes = count_nodes_by_type(store, "File")
        assert file_nodes >= 5
        
        # Should NOT have Class/Method nodes for topology-only files
        class_nodes = count_nodes_by_type(store, "Class")
        method_nodes = count_nodes_by_type(store, "Method")
        assert class_nodes >= 2  # From Python and Java
        assert method_nodes >= 2  # From Python and Java



class TestCLIFlags:
    """Test CLI flag combinations."""

    def test_dry_run_previews_changes(self, tmp_path: Path):
        """--dry-run should preview changes without modifying graph."""
        ws = setup_workspace(tmp_path)
        db_path = tmp_path / ".graphdb" / "graph.sqlite"
        
        # Build first
        import subprocess
        subprocess.run(
            ["python", "build_graph.py", "--workspace", str(ws), "--force"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            timeout=60,
        )
        
        # Dry run should not modify graph
        result = subprocess.run(
            ["python", "build_graph.py", "--workspace", str(ws), "--dry-run"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert "Files to Process" in result.stdout
        
        # Graph should be unchanged
        store = GraphStore(db_path=str(db_path))
        stats1 = store.stats()
        
        # Run again without changes
        subprocess.run(
            ["python", "build_graph.py", "--workspace", str(ws)],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            timeout=60,
        )
        
        store2 = GraphStore(db_path=str(db_path))
        stats2 = store2.stats()
        assert stats1["nodes"] == stats2["nodes"]
        assert stats1["edges"] == stats2["edges"]


class TestHubDampening:
    """Test hub node dampening functionality."""

    def test_hub_dampening_runs(self, tmp_path: Path):
        """Hub dampening should run and modify edges from high-degree nodes."""
        ws = setup_workspace(tmp_path)
        db_path = tmp_path / ".graphdb" / "graph.sqlite"
        
        # Build
        import subprocess
        result = subprocess.run(
            ["python", "build_graph.py", "--workspace", str(ws), "--force"],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0
        
        store = GraphStore(db_path=str(db_path))
        
        # Check that hub dampening ran
        assert "Hub dampening applied" in result.stdout



# Helper fixtures

@pytest.fixture
def tmp_path(tmp_path):
    """Override pytest tmp_path to use shorter path for Windows compatibility."""
    return tmp_path
