"""Unit tests for src/graph/extractor.py — language-agnostic structural extractor.

Covers:
- Query loading for each installed language
- Node/edge extraction on Java and Python fixtures
- Nesting and `contains` edges
- Performance on a 5000-line Java file (<500ms)
- No language-specific branching in extractor module
"""

import os
import time
from pathlib import Path

import pytest

from src.graph.extractor import (
    NodeRecord,
    EdgeRecord,
    _CAPTURE_SCHEMA,
    _load_query,
    extract_from_file,
)
from src.graph.parsers import get_parser, supported_languages

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Paths
ROOT = Path(__file__).resolve().parent.parent
QUERIES_DIR = str(ROOT / "queries")
FIXTURES_DIR = ROOT / "tests" / "fixtures" / "mini_workspace"

# Java fixture source
JAVA_USER_SERVICE = (FIXTURES_DIR / "UserService.java").read_bytes()
JAVA_USER = (FIXTURES_DIR / "User.java").read_bytes()

# Python fixture source
PYTHON_DATA_PROCESSOR = (FIXTURES_DIR / "data_processor.py").read_bytes()

# Languages actually installed
INSTALLED = {"java", "python"}


# ---------------------------------------------------------------------------
# Test: _CAPTURE_SCHEMA structure
# ---------------------------------------------------------------------------

def test_capture_schema_has_expected_keys():
    """_CAPTURE_SCHEMA contains all expected capture prefixes."""
    expected = {
        "module.def", "class.def", "class.name",
        "method.def", "method.name",
        "field.def", "field.name",
        "call.site", "call.target",
        "import.site", "import.path",
        "extends.target", "implements.target",
        "annotation.name",
    }
    assert set(_CAPTURE_SCHEMA.keys()) == expected


def test_capture_schema_values():
    """Each value in _CAPTURE_SCHEMA is a (kind, type) tuple."""
    for key, (kind, graph_type) in _CAPTURE_SCHEMA.items():
        assert kind in ("node", "edge", "metadata"), f"{key}: bad kind {kind}"
        assert isinstance(graph_type, str), f"{key}: bad type {graph_type}"


# ---------------------------------------------------------------------------
# Test: query loading
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lang", INSTALLED)
def test_query_loads_for_installed_language(lang):
    """The .scm file for each installed language loads and compiles."""
    loaded = get_parser(lang)
    if loaded is None:
        pytest.skip(f"{lang} parser not installed")
    _, language = loaded
    query = _load_query(lang, QUERIES_DIR, language)
    assert query is not None


def test_query_returns_none_for_missing_language():
    """_load_query returns None when the .scm file does not exist."""
    from tree_sitter import Language, Parser
    # Use a dummy language object
    import tree_sitter_python
    lang = Language(tree_sitter_python.language())
    query = _load_query("rust", QUERIES_DIR, lang)
    assert query is None


# ---------------------------------------------------------------------------
# Test: extract_from_file returns NodeRecord and EdgeRecord
# ---------------------------------------------------------------------------

def test_extract_java_user_service_produces_nodes():
    """UserService.java should produce Class and Method nodes."""
    nodes, edges = extract_from_file(
        file_path=str(FIXTURES_DIR / "UserService.java"),
        source_bytes=JAVA_USER_SERVICE,
        language="java",
        queries_dir=QUERIES_DIR,
    )
    assert len(nodes) > 0, "Expected at least one node from UserService.java"

    # Should have a Class node
    class_nodes = [n for n in nodes if n.type == "Class"]
    assert len(class_nodes) >= 1, "Expected at least one Class node"

    # The class should be named UserService
    class_names = [n.name for n in class_nodes]
    assert "UserService" in class_names, f"Expected 'UserService' in {class_names}"


def test_extract_java_user_service_produces_method_nodes():
    """UserService.java should produce Method nodes for its methods."""
    nodes, edges = extract_from_file(
        file_path=str(FIXTURES_DIR / "UserService.java"),
        source_bytes=JAVA_USER_SERVICE,
        language="java",
        queries_dir=QUERIES_DIR,
    )
    method_nodes = [n for n in nodes if n.type == "Method"]
    method_names_list = [n.name for n in method_nodes]
    assert len(method_nodes) >= 3, (
        f"Expected >= 3 methods, got {len(method_nodes)}: {method_names_list}"
    )


def test_extract_java_user_service_produces_contains_edges():
    """Each method should have a `contains` edge from its enclosing class."""
    nodes, edges = extract_from_file(
        file_path=str(FIXTURES_DIR / "UserService.java"),
        source_bytes=JAVA_USER_SERVICE,
        language="java",
        queries_dir=QUERIES_DIR,
    )
    contains_edges = [e for e in edges if e.relation == "contains"]
    assert len(contains_edges) >= 3, (
        f"Expected >= 3 contains edges, got {len(contains_edges)}"
    )

    # Each contains edge source should be the Class node
    class_ids = {n.id for n in nodes if n.type == "Class"}
    for ce in contains_edges:
        assert ce.source_id in class_ids, (
            f"Contains edge source {ce.source_id} not a Class node"
        )


def test_extract_java_user_service_produces_calls_edges():
    """UserService.java should produce `calls` edges for method_invocation nodes."""
    nodes, edges = extract_from_file(
        file_path=str(FIXTURES_DIR / "UserService.java"),
        source_bytes=JAVA_USER_SERVICE,
        language="java",
        queries_dir=QUERIES_DIR,
    )
    call_edges = [e for e in edges if e.relation == "calls"]
    # findByEmail, filter, equals, orElse, save, findById are all calls
    assert len(call_edges) >= 3, (
        f"Expected >= 3 calls edges, got {len(call_edges)}"
    )

    # Call edges should have confidence=0.5 (unresolved)
    for ce in call_edges:
        assert ce.metadata.get("confidence") == 0.5, (
            f"Call edge should have confidence=0.5, got {ce.metadata}"
        )


def test_extract_java_user_produces_class_and_fields():
    """User.java should produce Class and Field nodes."""
    nodes, edges = extract_from_file(
        file_path=str(FIXTURES_DIR / "User.java"),
        source_bytes=JAVA_USER,
        language="java",
        queries_dir=QUERIES_DIR,
    )
    class_nodes = [n for n in nodes if n.type == "Class"]
    assert len(class_nodes) >= 1
    assert any(n.name == "User" for n in class_nodes)

    field_nodes = [n for n in nodes if n.type == "Field"]
    field_names_list = [n.name for n in field_nodes]
    assert len(field_nodes) >= 4, (
        f"Expected >= 4 fields (id, email, username, passwordHash), "
        f"got {len(field_nodes)}: {field_names_list}"
    )


def test_extract_python_data_processor_produces_nodes():
    """data_processor.py should produce Method nodes for top-level functions."""
    nodes, edges = extract_from_file(
        file_path=str(FIXTURES_DIR / "data_processor.py"),
        source_bytes=PYTHON_DATA_PROCESSOR,
        language="python",
        queries_dir=QUERIES_DIR,
    )
    method_nodes = [n for n in nodes if n.type == "Method"]
    method_names = [n.name for n in method_nodes]
    assert "process_data" in method_names, f"Expected 'process_data' in {method_names}"
    assert "load_config" in method_names, f"Expected 'load_config' in {method_names}"
    assert "save_result" in method_names, f"Expected 'save_result' in {method_names}"


def test_extract_python_produces_calls_edges():
    """data_processor.py should produce `calls` edges for function calls."""
    nodes, edges = extract_from_file(
        file_path=str(FIXTURES_DIR / "data_processor.py"),
        source_bytes=PYTHON_DATA_PROCESSOR,
        language="python",
        queries_dir=QUERIES_DIR,
    )
    call_edges = [e for e in edges if e.relation == "calls"]
    # json.load, json.dump, open, len, .get, .append are all calls
    assert len(call_edges) >= 3, (
        f"Expected >= 3 calls edges, got {len(call_edges)}"
    )


def test_extract_python_produces_import_edges():
    """data_processor.py should produce `imports` edges."""
    nodes, edges = extract_from_file(
        file_path=str(FIXTURES_DIR / "data_processor.py"),
        source_bytes=PYTHON_DATA_PROCESSOR,
        language="python",
        queries_dir=QUERIES_DIR,
    )
    import_edges = [e for e in edges if e.relation == "imports"]
    assert len(import_edges) >= 1, (
        f"Expected >= 1 import edge, got {len(import_edges)}"
    )


# ---------------------------------------------------------------------------
# Test: record dataclasses
# ---------------------------------------------------------------------------

def test_node_record_defaults():
    """NodeRecord should have sensible defaults."""
    n = NodeRecord(
        id="X", type="Class", name="X",
        file_path="f.java", line_start=1, line_end=10,
    )
    assert n.metadata == {}


def test_edge_record_defaults():
    """EdgeRecord should have sensible defaults."""
    e = EdgeRecord(
        source_id="A", target_id="B", relation="calls",
        evidence_path="f.java", evidence_line=5,
    )
    assert e.metadata == {}


# ---------------------------------------------------------------------------
# Test: no language-specific branching in extractor
# ---------------------------------------------------------------------------

def test_no_language_specific_branching():
    """extractor.py must not contain 'if language ==' anywhere."""
    extractor_path = Path(__file__).resolve().parent.parent / "src" / "graph" / "extractor.py"
    source = extractor_path.read_text(encoding="utf-8")
    assert 'if language ==' not in source, (
        "extractor.py contains language-specific branching"
    )
    assert 'if language==' not in source, (
        "extractor.py contains language-specific branching"
    )


# ---------------------------------------------------------------------------
# Test: returns empty for unsupported language
# ---------------------------------------------------------------------------

def test_extract_unsupported_language_returns_empty():
    """extract_from_file returns ([], []) for an unsupported language."""
    nodes, edges = extract_from_file(
        file_path="dummy.go",
        source_bytes=b"package main",
        language="go",
        queries_dir=QUERIES_DIR,
    )
    # Go parser is not installed in the test environment
    assert nodes == []
    assert edges == []


def test_extract_missing_query_returns_empty():
    """extract_from_file returns ([], []) when the .scm file is missing."""
    # Use java language but point to a directory with no java.scm
    nodes, edges = extract_from_file(
        file_path="dummy.java",
        source_bytes=b"public class X {}",
        language="java",
        queries_dir="/tmp/nonexistent_queries_dir_xyz",
    )
    assert nodes == []
    assert edges == []


# ---------------------------------------------------------------------------
# Test: nesting and contains edges
# ---------------------------------------------------------------------------

def test_contains_edges_connect_class_to_methods():
    """Contains edges should connect Class nodes to Method (or Field) nodes."""
    nodes, edges = extract_from_file(
        file_path=str(FIXTURES_DIR / "UserService.java"),
        source_bytes=JAVA_USER_SERVICE,
        language="java",
        queries_dir=QUERIES_DIR,
    )
    contains_edges = [e for e in edges if e.relation == "contains"]

    class_ids = {n.id for n in nodes if n.type == "Class"}
    member_ids = {n.id for n in nodes if n.type in ("Method", "Field")}

    for ce in contains_edges:
        assert ce.source_id in class_ids, (
            f"Contains edge source {ce.source_id} should be a Class"
        )
        assert ce.target_id in member_ids, (
            f"Contains edge target {ce.target_id} should be a Method or Field"
        )


def test_each_method_has_contains_edge():
    """Every method node should be the target of at least one contains edge."""
    nodes, edges = extract_from_file(
        file_path=str(FIXTURES_DIR / "UserService.java"),
        source_bytes=JAVA_USER_SERVICE,
        language="java",
        queries_dir=QUERIES_DIR,
    )
    method_ids = {n.id for n in nodes if n.type == "Method"}
    contains_targets = {e.target_id for e in edges if e.relation == "contains"}

    for mid in method_ids:
        assert mid in contains_targets, (
            f"Method {mid} has no contains edge"
        )


# ---------------------------------------------------------------------------
# Test: performance on large file
# ---------------------------------------------------------------------------

def _generate_large_java_file(num_lines: int) -> bytes:
    """Generate a synthetic Java file with approximately num_lines lines."""
    lines = [
        "package com.example.large;",
        "",
        "import java.util.List;",
        "import java.util.Optional;",
        "",
        "public class LargeService {",
    ]
    method_template = """
    public void method_{0}(int param) {{
        int x = 0;
        x = x + 1;
        x = x + 2;
        x = x + 3;
        x = x + 4;
        x = x + 5;
        x = x + 6;
        x = x + 7;
        x = x + 8;
        x = x + 9;
        if (x > 0) {{
            x = x - 1;
        }}
    }}
"""
    for i in range(num_lines // 15):
        lines.append(method_template.format(i))
    lines.append("}")
    return "\n".join(lines).encode("utf-8")


def test_performance_5000_line_java_file():
    """extract_from_file on a 5000-line Java file completes in < 500ms."""
    large_source = _generate_large_java_file(5000)
    file_path = "LargeService.java"

    # Warm-up: parse once to load parser cache
    extract_from_file(file_path, large_source, "java", QUERIES_DIR)

    # Timed run
    start = time.perf_counter()
    for _ in range(3):
        extract_from_file(file_path, large_source, "java", QUERIES_DIR)
    elapsed = (time.perf_counter() - start) / 3  # average

    assert elapsed < 0.5, (
        f"Extraction took {elapsed:.3f}s, expected < 0.5s"
    )

    # Also verify it produced some output
    nodes, edges = extract_from_file(
        file_path, large_source, "java", QUERIES_DIR
    )
    assert len(nodes) >= 1, "Expected at least one node from large file"
    class_nodes = [n for n in nodes if n.type == "Class"]
    assert len(class_nodes) >= 1


# ---------------------------------------------------------------------------
# Test: calls edges have target names
# ---------------------------------------------------------------------------

def test_calls_edges_have_target_names():
    """Call edges should have target names in their metadata."""
    nodes, edges = extract_from_file(
        file_path=str(FIXTURES_DIR / "UserService.java"),
        source_bytes=JAVA_USER_SERVICE,
        language="java",
        queries_dir=QUERIES_DIR,
    )
    call_edges = [e for e in edges if e.relation == "calls"]
    for ce in call_edges:
        raw_name = ce.metadata.get("raw_name")
        assert raw_name and len(raw_name) > 0, (
            f"Call edge missing raw_name: {ce}"
        )


def test_calls_target_ids_contain_raw_name():
    """Call edge target_id should contain the raw target name."""
    nodes, edges = extract_from_file(
        file_path=str(FIXTURES_DIR / "UserService.java"),
        source_bytes=JAVA_USER_SERVICE,
        language="java",
        queries_dir=QUERIES_DIR,
    )
    call_edges = [e for e in edges if e.relation == "calls"]
    for ce in call_edges:
        raw_name = ce.metadata.get("raw_name", "")
        assert raw_name in ce.target_id, (
            f"Target {ce.target_id} should contain raw_name {raw_name}"
        )


# ---------------------------------------------------------------------------
# Test: evidence tracking
# ---------------------------------------------------------------------------

def test_edges_have_evidence():
    """All edges should have evidence_path and evidence_line set."""
    nodes, edges = extract_from_file(
        file_path=str(FIXTURES_DIR / "UserService.java"),
        source_bytes=JAVA_USER_SERVICE,
        language="java",
        queries_dir=QUERIES_DIR,
    )
    for e in edges:
        assert e.evidence_path, f"Edge missing evidence_path: {e}"
        assert e.evidence_line > 0, f"Edge missing evidence_line: {e}"


def test_nodes_have_line_numbers():
    """All nodes should have valid line numbers."""
    nodes, edges = extract_from_file(
        file_path=str(FIXTURES_DIR / "UserService.java"),
        source_bytes=JAVA_USER_SERVICE,
        language="java",
        queries_dir=QUERIES_DIR,
    )
    for n in nodes:
        assert n.line_start > 0, f"Node {n.id} has invalid line_start"
        assert n.line_end >= n.line_start, (
            f"Node {n.id} has line_end < line_start"
        )


# ---------------------------------------------------------------------------
# Test: idempotency
# ---------------------------------------------------------------------------

def test_extract_is_idempotent():
    """Running extract_from_file twice on the same input produces identical results."""
    nodes1, edges1 = extract_from_file(
        file_path=str(FIXTURES_DIR / "UserService.java"),
        source_bytes=JAVA_USER_SERVICE,
        language="java",
        queries_dir=QUERIES_DIR,
    )
    nodes2, edges2 = extract_from_file(
        file_path=str(FIXTURES_DIR / "UserService.java"),
        source_bytes=JAVA_USER_SERVICE,
        language="java",
        queries_dir=QUERIES_DIR,
    )

    node_ids_1 = {n.id for n in nodes1}
    node_ids_2 = {n.id for n in nodes2}
    assert node_ids_1 == node_ids_2, "Node IDs should be identical across runs"

    edge_keys_1 = {(e.source_id, e.target_id, e.relation) for e in edges1}
    edge_keys_2 = {(e.source_id, e.target_id, e.relation) for e in edges2}
    assert edge_keys_1 == edge_keys_2, "Edge keys should be identical across runs"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
