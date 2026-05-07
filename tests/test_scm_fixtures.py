"""Tests for .scm query files and test fixtures.

For each language (java, python, javascript, typescript, go):
  - Run the extractor against each fixture file.
  - Verify that the expected number of class.def, method.def, and call.site
    captures are produced.

This test enforces that every .scm file produces structurally meaningful
output for its language's common patterns.
"""

import pytest
from pathlib import Path

from src.graph.extractor import extract_from_file, NodeRecord, EdgeRecord

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
QUERIES_DIR = ROOT / "queries"
FIXTURES_DIR = QUERIES_DIR / "_test_fixtures"

# ---------------------------------------------------------------------------
# Fixture definitions: language -> {fixture_name -> {expected counts}}
# ---------------------------------------------------------------------------

# Expected minimum counts per fixture.
# Format: {"class": N, "method": N, "call": N}
# These are MINIMUMS — if the .scm captures more, the test still passes.
# The key is that the .scm captures AT LEAST these structural elements.

FIXTURE_EXPECTATIONS = {
    "java": {
        "simple":       {"class": 1, "method": 2, "call": 0},
        "generics":     {"class": 1, "method": 3, "call": 0},
        "annotations":  {"class": 1, "method": 1, "call": 0},
        "nested":       {"class": 2, "method": 2, "call": 0},
        "calls":        {"class": 1, "method": 3, "call": 4},
    },
    "python": {
        "simple":     {"class": 1, "method": 4, "call": 0},
        "decorators": {"class": 1, "method": 5, "call": 0},
        "async":      {"class": 1, "method": 3, "call": 0},
        "dataclass":  {"class": 2, "method": 3, "call": 0},
        "calls":      {"class": 1, "method": 4, "call": 6},
    },
    "javascript": {
        "simple":  {"class": 1, "method": 4, "call": 0},
        "classes": {"class": 3, "method": 5, "call": 0},
        "methods": {"class": 1, "method": 5, "call": 0},
        "calls":   {"class": 1, "method": 4, "call": 2},
    },
    "typescript": {
        "simple":  {"class": 1, "method": 4, "call": 0},
        "classes": {"class": 3, "method": 6, "call": 0},
        "methods": {"class": 1, "method": 5, "call": 0},
        "calls":   {"class": 1, "method": 4, "call": 3},
    },
    "go": {
        "simple":  {"class": 1, "method": 3, "call": 0},
        "structs": {"class": 3, "method": 3, "call": 0},
        "methods": {"class": 1, "method": 4, "call": 0},
        "calls":   {"class": 1, "method": 4, "call": 4},
    },
}

# Extensions used to derive language for topology layer (not structural).
EXT_MAP = {
    ".java": "java",
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".go": "go",
}


def _fixture_path(lang: str, name: str) -> Path:
    """Return the path to a fixture file."""
    ext_map = {
        "java": ".java",
        "python": ".py",
        "javascript": ".js",
        "typescript": ".ts",
        "go": ".go",
    }
    return FIXTURES_DIR / lang / f"{name}{ext_map[lang]}"


def _count_nodes(nodes: list[NodeRecord], node_type: str) -> int:
    """Count nodes of a given graph type."""
    return sum(1 for n in nodes if n.type == node_type)


def _count_edges(edges: list[EdgeRecord], relation: str) -> int:
    """Count edges of a given relation type."""
    return sum(1 for e in edges if e.relation == relation)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSCMFixtures:
    """Verify each .scm produces expected captures for its fixtures."""

    @pytest.mark.parametrize("lang", FIXTURE_EXPECTATIONS.keys())
    def test_scm_exists(self, lang: str):
        """Each language must have a .scm file."""
        scm_path = QUERIES_DIR / f"{lang}.scm"
        assert scm_path.exists(), f"Missing .scm file: {scm_path}"

    @pytest.mark.parametrize("fixture_name", FIXTURE_EXPECTATIONS["java"].keys())
    def test_java_fixtures(self, fixture_name: str):
        """Java fixtures produce expected structural captures."""
        self._run_fixture_test("java", fixture_name)

    @pytest.mark.parametrize("fixture_name", FIXTURE_EXPECTATIONS["python"].keys())
    def test_python_fixtures(self, fixture_name: str):
        """Python fixtures produce expected structural captures."""
        self._run_fixture_test("python", fixture_name)

    @pytest.mark.parametrize("fixture_name", FIXTURE_EXPECTATIONS["javascript"].keys())
    def test_javascript_fixtures(self, fixture_name: str):
        """JavaScript fixtures produce expected structural captures."""
        self._run_fixture_test("javascript", fixture_name)

    @pytest.mark.parametrize("fixture_name", FIXTURE_EXPECTATIONS["typescript"].keys())
    def test_typescript_fixtures(self, fixture_name: str):
        """TypeScript fixtures produce expected structural captures."""
        self._run_fixture_test("typescript", fixture_name)

    @pytest.mark.parametrize("fixture_name", FIXTURE_EXPECTATIONS["go"].keys())
    def test_go_fixtures(self, fixture_name: str):
        """Go fixtures produce expected structural captures."""
        self._run_fixture_test("go", fixture_name)

    def _run_fixture_test(self, lang: str, fixture_name: str) -> None:
        """Run the extractor on a single fixture and verify counts."""
        fixture_path = _fixture_path(lang, fixture_name)
        assert fixture_path.exists(), f"Missing fixture: {fixture_path}"

        source = fixture_path.read_bytes()
        file_rel = str(fixture_path.relative_to(ROOT))

        nodes, edges = extract_from_file(
            file_path=file_rel,
            source_bytes=source,
            language=lang,
            queries_dir=str(QUERIES_DIR),
        )

        expected = FIXTURE_EXPECTATIONS[lang][fixture_name]

        class_count = _count_nodes(nodes, "Class")
        method_count = _count_nodes(nodes, "Method")
        call_count = _count_edges(edges, "calls")

        # Verify minimum class count
        assert class_count >= expected["class"], (
            f"{lang}/{fixture_name}: expected >= {expected['class']} Class nodes, "
            f"got {class_count}. Nodes: {[n.name for n in nodes if n.type == 'Class']}"
        )

        # Verify minimum method count
        assert method_count >= expected["method"], (
            f"{lang}/{fixture_name}: expected >= {expected['method']} Method nodes, "
            f"got {method_count}. Nodes: {[n.name for n in nodes if n.type == 'Method']}"
        )

        # Verify minimum call count
        assert call_count >= expected["call"], (
            f"{lang}/{fixture_name}: expected >= {expected['call']} call edges, "
            f"got {call_count}. Edges: {[(e.source_id, e.relation, e.target_id) for e in edges]}"
        )


class TestSCMStructure:
    """Verify .scm files use the universal capture vocabulary."""

    @pytest.mark.parametrize("lang", FIXTURE_EXPECTATIONS.keys())
    def test_scm_uses_class_def(self, lang: str):
        """Each .scm must capture @class.def."""
        scm_path = QUERIES_DIR / f"{lang}.scm"
        content = scm_path.read_text(encoding="utf-8")
        assert "@class.def" in content, f"{lang}.scm missing @class.def"

    @pytest.mark.parametrize("lang", FIXTURE_EXPECTATIONS.keys())
    def test_scm_uses_method_def(self, lang: str):
        """Each .scm must capture @method.def."""
        scm_path = QUERIES_DIR / f"{lang}.scm"
        content = scm_path.read_text(encoding="utf-8")
        assert "@method.def" in content, f"{lang}.scm missing @method.def"

    @pytest.mark.parametrize("lang", FIXTURE_EXPECTATIONS.keys())
    def test_scm_uses_call_site(self, lang: str):
        """Each .scm must capture @call.site."""
        scm_path = QUERIES_DIR / f"{lang}.scm"
        content = scm_path.read_text(encoding="utf-8")
        assert "@call.site" in content, f"{lang}.scm missing @call.site"


class TestLanguageParity:
    """Verify that all languages produce comparable output shapes.

    For a "simple class with one method" fixture in each language,
    the graph must have the same structural shape:
      - 1 Class node
      - 1 Method node
      - 1 contains edge
    """

    SIMPLE_FIXTURES = {
        "java": "simple.java",
        "python": "simple.py",
        "javascript": "simple.js",
        "typescript": "simple.ts",
        "go": "simple.go",
    }

    @pytest.mark.parametrize("lang,fixture_file", SIMPLE_FIXTURES.items())
    def test_simple_parity(self, lang: str, fixture_file: str):
        """All languages produce 1 Class + 1+ Method for simple fixtures."""
        fixture_path = FIXTURES_DIR / lang / fixture_file
        source = fixture_path.read_bytes()
        file_rel = str(fixture_path.relative_to(ROOT))

        nodes, edges = extract_from_file(
            file_path=file_rel,
            source_bytes=source,
            language=lang,
            queries_dir=str(QUERIES_DIR),
        )

        class_count = _count_nodes(nodes, "Class")
        method_count = _count_nodes(nodes, "Method")

        assert class_count >= 1, (
            f"{lang}: simple fixture should have >= 1 Class, got {class_count}"
        )
        assert method_count >= 1, (
            f"{lang}: simple fixture should have >= 1 Method, got {method_count}"
        )

        # Verify contains edges exist
        contains_edges = [e for e in edges if e.relation == "contains"]
        assert len(contains_edges) >= 1, (
            f"{lang}: simple fixture should have >= 1 contains edge, got {len(contains_edges)}"
        )
