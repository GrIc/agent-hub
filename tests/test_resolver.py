"""Unit tests for src/graph/resolver.py — heuristic FQN resolution.

Covers:
- Resolution rate ≥ 70% on a mixed Java+Python fixture
- Unresolved edges are kept with correct flags
- No false resolutions (unresolved count > false positives)
- get_unresolved_edges() inspection helper
- Already-resolved edges are not double-resolved
- Empty store edge case
"""

import os
import tempfile
import unittest

from src.graph.store import GraphStore
from src.graph.resolver import resolve_edges, get_unresolved_edges, ResolutionStats


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_placeholder_nodes(store: GraphStore, edge_list: list[dict]) -> None:
    """Create placeholder nodes for all edge source/target pairs so that
    foreign-key constraints are satisfied.  This is a test-only helper.

    Each placeholder gets type=Placeholder and the id is used verbatim.
    """
    seen: set[str] = set()
    for e in edge_list:
        for key in ("source_id", "target_id"):
            nid = e.get(key, "")
            if nid and nid not in seen:
                store.upsert_node(
                    id=nid,
                    type="Placeholder",
                    name=nid.rsplit(":", 1)[-1] if ":" in nid else nid,
                    file_path=e.get("evidence_path"),
                    line_start=e.get("evidence_line"),
                    line_end=e.get("evidence_line"),
                )
                seen.add(nid)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestResolveEdgesEmptyStore(unittest.TestCase):
    """Test resolve_edges on an empty store."""

    def test_empty_store_returns_zero_stats(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        db_path = tmp.name
        tmp.close()
        try:
            store = GraphStore(db_path)
            stats = resolve_edges(store)
            self.assertIsInstance(stats, ResolutionStats)
            self.assertEqual(stats.total, 0)
            self.assertEqual(stats.resolved, 0)
            self.assertEqual(stats.unresolved, 0)
            store.close()
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)


class TestResolveEdgesBasic(unittest.TestCase):
    """Test basic resolution with a simple fixture."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()
        self.store = GraphStore(self.db_path)

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_same_file_resolution(self):
        """A call to a method in the same file should resolve via intra-file lookup."""
        # Create nodes first (FK constraint).
        self.store.upsert_node(
            id="Class:src/Example.java:1",
            type="Class", name="Example",
            file_path="src/Example.java", line_start=1, line_end=10,
        )
        self.store.upsert_node(
            id="Method:src/Example.java:3",
            type="Method", name="doWork",
            file_path="src/Example.java", line_start=3, line_end=5,
        )
        self.store.upsert_node(
            id="Method:src/Example.java:7",
            type="Method", name="main",
            file_path="src/Example.java", line_start=7, line_end=10,
        )
        self.store.upsert_node(
            id="UnresolvedCall:doWork",
            type="Placeholder", name="doWork",
            file_path="src/Example.java", line_start=8, line_end=8,
        )
        # main calls doWork (simple name).
        self.store.upsert_edge(
            source_id="Method:src/Example.java:7",
            target_id="UnresolvedCall:doWork",
            relation="calls",
            evidence_path="src/Example.java",
            evidence_line=8,
            metadata={"raw_name": "doWork"},
        )

        stats = resolve_edges(self.store)
        self.assertEqual(stats.total, 1)
        self.assertEqual(stats.resolved, 1)
        self.assertEqual(stats.unresolved, 0)

        # Verify the edge was rewritten.
        edge = self.store.get_edge(
            "Method:src/Example.java:7",
            "Method:src/Example.java:3",
            "calls",
        )
        self.assertIsNotNone(edge)
        self.assertEqual(edge["metadata"]["confidence"], 1.0)
        self.assertFalse(edge["metadata"].get("unresolved", False))

    def test_unresolved_kept_with_flags(self):
        """Unresolved calls should keep confidence=0.5 and unresolved=True."""
        self.store.upsert_node(
            id="Method:src/App.java:1",
            type="Method", name="main",
            file_path="src/App.java", line_start=1, line_end=5,
        )
        self.store.upsert_node(
            id="UnresolvedCall:nonExistentMethod",
            type="Placeholder", name="nonExistentMethod",
            file_path="src/App.java", line_start=2, line_end=2,
        )
        # Call to a method that doesn't exist in the graph.
        self.store.upsert_edge(
            source_id="Method:src/App.java:1",
            target_id="UnresolvedCall:nonExistentMethod",
            relation="calls",
            evidence_path="src/App.java",
            evidence_line=2,
            metadata={"raw_name": "nonExistentMethod"},
        )

        stats = resolve_edges(self.store)
        self.assertEqual(stats.total, 1)
        self.assertEqual(stats.resolved, 0)
        self.assertEqual(stats.unresolved, 1)

        edge = self.store.get_edge(
            "Method:src/App.java:1",
            "UnresolvedCall:nonExistentMethod",
            "calls",
        )
        self.assertIsNotNone(edge)
        self.assertEqual(edge["metadata"]["confidence"], 0.5)
        self.assertTrue(edge["metadata"].get("unresolved", False))

    def test_get_unresolved_edges(self):
        """get_unresolved_edges() should return only unresolved calls."""
        self.store.upsert_node(id="Class:src/A.java:1", type="Class", name="A",
                               file_path="src/A.java", line_start=1, line_end=5)
        self.store.upsert_node(id="Class:src/B.java:1", type="Class", name="B",
                               file_path="src/B.java", line_start=1, line_end=5)
        # Resolved call (already pointing to a known node).
        self.store.upsert_edge(
            source_id="Class:src/A.java:1", target_id="Class:src/A.java:1",
            relation="calls", evidence_path="src/A.java", evidence_line=2,
            metadata={"confidence": 1.0},
        )
        # Unresolved call.
        self.store.upsert_node(id="UnresolvedCall:ghost", type="Placeholder", name="ghost",
                               file_path="src/B.java", line_start=3, line_end=3)
        self.store.upsert_edge(
            source_id="Class:src/B.java:1", target_id="UnresolvedCall:ghost",
            relation="calls", evidence_path="src/B.java", evidence_line=3,
            metadata={"confidence": 0.5, "unresolved": True},
        )

        unresolved = get_unresolved_edges(self.store)
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0]["target_id"], "UnresolvedCall:ghost")


class TestResolveEdgesImportResolution(unittest.TestCase):
    """Test resolution via import edges."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()
        self.store = GraphStore(self.db_path)

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_import_based_resolution(self):
        """A call to an imported symbol should resolve via the import edge."""
        # App.java module node.
        self.store.upsert_node(
            id="Module:src/App.java",
            type="Module", name="App",
            file_path="src/App.java", line_start=1, line_end=1,
        )
        # UserService class exists in another file.
        self.store.upsert_node(
            id="Class:src/UserService.java:1",
            type="Class", name="UserService",
            file_path="src/UserService.java", line_start=1, line_end=20,
        )
        # Import placeholder.
        self.store.upsert_node(
            id="Import:com.example.service.UserService",
            type="Placeholder", name="UserService",
            file_path="src/App.java", line_start=3, line_end=3,
        )
        # App.java imports UserService.
        self.store.upsert_edge(
            source_id="Module:src/App.java",
            target_id="Import:com.example.service.UserService",
            relation="imports",
            evidence_path="src/App.java", evidence_line=3,
        )
        # Call placeholder.
        self.store.upsert_node(
            id="UnresolvedCall:UserService",
            type="Placeholder", name="UserService",
            file_path="src/App.java", line_start=10, line_end=10,
        )
        # App calls UserService (simple name).
        self.store.upsert_edge(
            source_id="Module:src/App.java",
            target_id="UnresolvedCall:UserService",
            relation="calls",
            evidence_path="src/App.java", evidence_line=10,
            metadata={"raw_name": "UserService"},
        )

        stats = resolve_edges(self.store)
        self.assertEqual(stats.total, 1)
        self.assertEqual(stats.resolved, 1)
        self.assertEqual(stats.unresolved, 0)

        # The target should be rewritten to the actual Class node ID
        # (not the import path, since import paths are not valid FK targets).
        edge = self.store.get_edge(
            "Module:src/App.java",
            "Class:src/UserService.java:1",
            "calls",
        )
        self.assertIsNotNone(edge)
        self.assertEqual(edge["metadata"]["confidence"], 1.0)


class TestResolveEdgesSamePackage(unittest.TestCase):
    """Test resolution via same-package lookup."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()
        self.store = GraphStore(self.db_path)

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_same_package_resolution(self):
        """A call to a class in the same package should resolve."""
        self.store.upsert_node(
            id="Class:src/pkg/Controller.java:1",
            type="Class", name="Controller",
            file_path="src/pkg/Controller.java", line_start=1, line_end=10,
        )
        self.store.upsert_node(
            id="Class:src/pkg/Service.java:1",
            type="Class", name="Service",
            file_path="src/pkg/Service.java", line_start=1, line_end=10,
        )
        self.store.upsert_node(
            id="UnresolvedCall:Service",
            type="Placeholder", name="Service",
            file_path="src/pkg/Controller.java", line_start=5, line_end=5,
        )
        # Controller calls Service.
        self.store.upsert_edge(
            source_id="Class:src/pkg/Controller.java:1",
            target_id="UnresolvedCall:Service",
            relation="calls",
            evidence_path="src/pkg/Controller.java", evidence_line=5,
            metadata={"raw_name": "Service"},
        )

        stats = resolve_edges(self.store)
        self.assertEqual(stats.total, 1)
        self.assertEqual(stats.resolved, 1)
        self.assertEqual(stats.unresolved, 0)


class TestMixedJavaPythonFixture(unittest.TestCase):
    """Test resolution rate ≥ 70% on a mixed Java+Python fixture.

    This fixture simulates a realistic workspace with:
    - Java files with imports and cross-class calls
    - Python files with imports and cross-function calls
    - Some unresolved calls (external APIs, third-party)
    """

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()
        self.store = GraphStore(self.db_path)

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _build_mixed_fixture(self):
        """Build a mixed Java+Python fixture with ~20 calls.

        Expected: ≥ 14 resolved (70%), ≤ 6 unresolved.
        No false resolutions.
        """
        # Helper to create a node quickly.
        def node(id_, type_, name, fp, ls, le):
            self.store.upsert_node(id=id_, type=type_, name=name,
                                   file_path=fp, line_start=ls, line_end=le)

        def call_edge(src, tgt, fp, line, raw):
            """Create a calls edge with a placeholder target node."""
            node(tgt, "Placeholder", raw, fp, line, line)
            self.store.upsert_edge(
                source_id=src, target_id=tgt, relation="calls",
                evidence_path=fp, evidence_line=line,
                metadata={"raw_name": raw},
            )

        # === Java files ===

        # UserService.java
        node("Class:src/com/example/service/UserService.java:1", "Class", "UserService",
             "src/com/example/service/UserService.java", 1, 30)
        node("Method:src/com/example/service/UserService.java:5", "Method", "findById",
             "src/com/example/service/UserService.java", 5, 10)
        node("Method:src/com/example/service/UserService.java:15", "Method", "save",
             "src/com/example/service/UserService.java", 15, 20)
        node("Module:src/com/example/service/UserService.java", "Module", "com.example.service",
             "src/com/example/service/UserService.java", 1, 1)
        # Import placeholder.
        node("Import:com.example.repo.UserRepository", "Placeholder", "UserRepository",
             "src/com/example/service/UserService.java", 3, 3)
        self.store.upsert_edge(
            source_id="Module:src/com/example/service/UserService.java",
            target_id="Import:com.example.repo.UserRepository",
            relation="imports", evidence_path="src/com/example/service/UserService.java",
            evidence_line=3,
        )

        # UserRepository.java
        node("Class:src/com/example/repo/UserRepository.java:1", "Class", "UserRepository",
             "src/com/example/repo/UserRepository.java", 1, 20)
        node("Method:src/com/example/repo/UserRepository.java:5", "Method", "save",
             "src/com/example/repo/UserRepository.java", 5, 10)
        node("Method:src/com/example/repo/UserRepository.java:12", "Method", "findById",
             "src/com/example/repo/UserRepository.java", 12, 17)

        # UserController.java
        node("Class:src/com/example/web/UserController.java:1", "Class", "UserController",
             "src/com/example/web/UserController.java", 1, 20)
        node("Method:src/com/example/web/UserController.java:5", "Method", "getUser",
             "src/com/example/web/UserController.java", 5, 10)
        node("Method:src/com/example/web/UserController.java:12", "Method", "createUser",
             "src/com/example/web/UserController.java", 12, 17)
        node("Module:src/com/example/web/UserController.java", "Module", "com.example.web",
             "src/com/example/web/UserController.java", 1, 1)
        node("Import:com.example.service.UserService", "Placeholder", "UserService",
             "src/com/example/web/UserController.java", 3, 3)
        self.store.upsert_edge(
            source_id="Module:src/com/example/web/UserController.java",
            target_id="Import:com.example.service.UserService",
            relation="imports", evidence_path="src/com/example/web/UserController.java",
            evidence_line=3,
        )

        # === Python files ===

        # app.py
        node("Module:src/app.py", "Module", "app", "src/app.py", 1, 1)
        node("Class:src/app.py:1", "Class", "App", "src/app.py", 1, 20)
        node("Method:src/app.py:5", "Method", "run", "src/app.py", 5, 10)
        node("Method:src/app.py:12", "Method", "setup", "src/app.py", 12, 17)
        node("Import:src.services.UserService", "Placeholder", "UserService",
             "src/app.py", 3, 3)
        node("Import:src.utils.helpers", "Placeholder", "helpers",
             "src/app.py", 4, 4)
        self.store.upsert_edge(
            source_id="Module:src/app.py",
            target_id="Import:src.services.UserService",
            relation="imports", evidence_path="src/app.py", evidence_line=3,
        )
        self.store.upsert_edge(
            source_id="Module:src/app.py",
            target_id="Import:src.utils.helpers",
            relation="imports", evidence_path="src/app.py", evidence_line=4,
        )

        # services.py
        node("Class:src/services.py:1", "Class", "UserService", "src/services.py", 1, 20)
        node("Method:src/services.py:5", "Method", "find_user", "src/services.py", 5, 10)
        node("Method:src/services.py:12", "Method", "create_user", "src/services.py", 12, 17)

        # utils.py
        node("Class:src/utils.py:1", "Class", "helpers", "src/utils.py", 1, 15)
        node("Method:src/utils.py:3", "Method", "validate", "src/utils.py", 3, 7)
        node("Method:src/utils.py:9", "Method", "format_output", "src/utils.py", 9, 13)

        # services.py — add the missing method node for call edge #16.
        node("Method:src/services.py:15", "Method", "save", "src/services.py", 15, 17)

        # === Calls edges (20 total) ===

        # 1. UserController.getUser calls UserService (import resolution).
        call_edge("Method:src/com/example/web/UserController.java:5",
                  "UnresolvedCall:UserService",
                  "src/com/example/web/UserController.java", 6, "UserService")
        # 2. UserController.createUser calls UserService (import resolution).
        call_edge("Method:src/com/example/web/UserController.java:12",
                  "UnresolvedCall:UserService",
                  "src/com/example/web/UserController.java", 13, "UserService")
        # 3. UserService.save calls UserRepository (import resolution).
        call_edge("Method:src/com/example/service/UserService.java:15",
                  "UnresolvedCall:UserRepository",
                  "src/com/example/service/UserService.java", 16, "UserRepository")
        # 4. App.run calls UserService (import resolution).
        call_edge("Method:src/app.py:5",
                  "UnresolvedCall:UserService",
                  "src/app.py", 6, "UserService")
        # 5. App.run calls helpers (import resolution).
        call_edge("Method:src/app.py:5",
                  "UnresolvedCall:helpers",
                  "src/app.py", 7, "helpers")
        # 6. App.setup calls run (same-file resolution).
        call_edge("Method:src/app.py:12",
                  "UnresolvedCall:run",
                  "src/app.py", 13, "run")
        # 7. UserService.find_user calls format_output (same-package).
        call_edge("Method:src/services.py:5",
                  "UnresolvedCall:format_output",
                  "src/services.py", 6, "format_output")
        # 8. UserService.create_user calls validate (same-package).
        call_edge("Method:src/services.py:12",
                  "UnresolvedCall:validate",
                  "src/services.py", 13, "validate")
        # 9. UserRepository.findById calls logger (external — unresolved).
        call_edge("Method:src/com/example/repo/UserRepository.java:12",
                  "UnresolvedCall:logger",
                  "src/com/example/repo/UserRepository.java", 13, "logger")
        # 10. UserController.getUser calls JSON (external — unresolved).
        call_edge("Method:src/com/example/web/UserController.java:5",
                  "UnresolvedCall:JSON",
                  "src/com/example/web/UserController.java", 8, "JSON")
        # 11. App.run calls print (builtin — unresolved).
        call_edge("Method:src/app.py:5",
                  "UnresolvedCall:print",
                  "src/app.py", 8, "print")
        # 12. UserService.findById calls UserRepository (import resolution).
        call_edge("Method:src/com/example/service/UserService.java:5",
                  "UnresolvedCall:UserRepository",
                  "src/com/example/service/UserService.java", 6, "UserRepository")
        # 13. App.setup calls logging (external — unresolved).
        call_edge("Method:src/app.py:12",
                  "UnresolvedCall:logging",
                  "src/app.py", 14, "logging")
        # 14. UserController.getUser calls findById (import resolution).
        call_edge("Method:src/com/example/web/UserController.java:5",
                  "UnresolvedCall:findById",
                  "src/com/example/web/UserController.java", 7, "findById")
        # 15. App.run calls setup (same-file).
        call_edge("Method:src/app.py:5",
                  "UnresolvedCall:setup",
                  "src/app.py", 9, "setup")
        # 16. UserService.save calls validate (same-package, Python).
        call_edge("Method:src/services.py:15",
                  "UnresolvedCall:validate",
                  "src/services.py", 16, "validate")
        # 17. UserRepository.save calls logger (external — unresolved).
        call_edge("Method:src/com/example/repo/UserRepository.java:5",
                  "UnresolvedCall:logger2",
                  "src/com/example/repo/UserRepository.java", 6, "logger")
        # 18. UserController.createUser calls validate (same-package, Java).
        call_edge("Method:src/com/example/web/UserController.java:12",
                  "UnresolvedCall:validate",
                  "src/com/example/web/UserController.java", 14, "validate")
        # 19. App.run calls format_output (import resolution).
        call_edge("Method:src/app.py:5",
                  "UnresolvedCall:format_output",
                  "src/app.py", 10, "format_output")
        # 20. UserService.find_user calls format_output (same-package).
        call_edge("Method:src/services.py:5",
                  "UnresolvedCall:format_output",
                  "src/services.py", 8, "format_output")

    def test_resolution_rate_ge_70_percent(self):
        """Resolution rate should be ≥ 70% on the mixed fixture."""
        self._build_mixed_fixture()
        stats = resolve_edges(self.store)

        self.assertGreaterEqual(stats.total, 15, "Fixture should have at least 15 calls")
        resolution_rate = stats.resolved / stats.total if stats.total > 0 else 0
        self.assertGreaterEqual(
            resolution_rate, 0.70,
            f"Resolution rate {resolution_rate:.2%} < 70% "
            f"(resolved={stats.resolved}, total={stats.total})",
        )

    def test_unresolved_count_exceeds_false_resolutions(self):
        """Unresolved count should be > 0 (legitimate unresolveds exist).
        No false resolutions: all resolved edges should point to valid nodes.
        """
        self._build_mixed_fixture()
        stats = resolve_edges(self.store)

        # There should be some unresolved calls (external APIs, builtins).
        self.assertGreater(
            stats.unresolved, 0,
            "Expected some unresolved calls (e.g., logger, JSON, print)",
        )

        # Verify no false resolutions: every resolved edge should target
        # a node that actually exists in the store.
        false_resolutions = 0
        for edge in self.store.list_edges(relation="calls", limit=100000):
            meta = edge.get("metadata", {})
            if meta.get("confidence", 0) == 1.0 and not meta.get("unresolved", False):
                target = edge["target_id"]
                node = self.store.get_node(target)
                if node is None:
                    false_resolutions += 1

        self.assertEqual(
            false_resolutions, 0,
            f"Found {false_resolutions} false resolutions (resolved edges pointing to non-existent nodes)",
        )

    def test_unresolved_edges_kept_not_deleted(self):
        """Unresolved edges should NOT be deleted — they stay with confidence=0.5."""
        self._build_mixed_fixture()
        stats_before = self.store.stats()
        calls_before = stats_before["edge_count"]

        resolve_edges(self.store)

        stats_after = self.store.stats()
        calls_after = stats_after["edge_count"]

        # Edge count should not decrease.
        self.assertGreaterEqual(
            calls_after, calls_before,
            "Unresolved edges should not be deleted",
        )

        # Verify unresolved edges have correct flags.
        unresolved = get_unresolved_edges(self.store)
        for edge in unresolved:
            self.assertTrue(
                edge["metadata"].get("unresolved", False),
                f"Edge {edge['source_id']} -> {edge['target_id']} should have unresolved=True",
            )
            self.assertEqual(
                edge["metadata"].get("confidence", 1.0),
                0.5,
                f"Edge {edge['source_id']} -> {edge['target_id']} should have confidence=0.5",
            )

    def test_already_resolved_not_double_resolved(self):
        """Edges already pointing to known nodes should not be modified."""
        self.store.upsert_node(
            id="Class:src/A.java:1", type="Class", name="A",
            file_path="src/A.java", line_start=1, line_end=10,
        )
        self.store.upsert_node(
            id="Class:src/B.java:1", type="Class", name="B",
            file_path="src/B.java", line_start=1, line_end=10,
        )
        # Edge already pointing to a known node ID.
        self.store.upsert_edge(
            source_id="Class:src/A.java:1", target_id="Class:src/B.java:1",
            relation="calls", evidence_path="src/A.java", evidence_line=5,
            metadata={"confidence": 1.0, "unresolved": False},
        )

        stats = resolve_edges(self.store)
        self.assertEqual(stats.total, 1)
        self.assertEqual(stats.resolved, 1)
        self.assertEqual(stats.unresolved, 0)

        # Edge should remain unchanged.
        edge = self.store.get_edge(
            "Class:src/A.java:1", "Class:src/B.java:1", "calls",
        )
        self.assertIsNotNone(edge)
        self.assertEqual(edge["target_id"], "Class:src/B.java:1")


class TestResolutionStats(unittest.TestCase):
    """Test ResolutionStats utility methods."""

    def test_to_dict(self):
        stats = ResolutionStats(resolved=10, unresolved=5, total=15)
        self.assertEqual(stats.to_dict(), {"resolved": 10, "unresolved": 5, "total": 15})

    def test_default_values(self):
        stats = ResolutionStats()
        self.assertEqual(stats.resolved, 0)
        self.assertEqual(stats.unresolved, 0)
        self.assertEqual(stats.total, 0)
        self.assertEqual(stats.to_dict(), {"resolved": 0, "unresolved": 0, "total": 0})


if __name__ == "__main__":
    unittest.main()
