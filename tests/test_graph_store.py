"""Unit tests for src/graph/store.py — SQLite-backed graph store.

Covers:
- upsert idempotency
- delete cascade (delete_for_file removes nodes + edges)
- callers/callees on a 100-node fixture
- shortest_path and preview_impact
- hub module detection
- file_state tracking
- meta operations
- context manager lifecycle
- DB persistence across reopen
"""

import json
import os
import tempfile
import unittest

from src.graph.store import GraphStore


class TestUpsertIdempotency(unittest.TestCase):
    """Test that upsert operations are idempotent."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()
        self.store = GraphStore(self.db_path)

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_upsert_node_idempotent(self):
        """Upserting the same node twice should not duplicate it."""
        self.store.upsert_node(
            id="Class:Foo.java:42",
            type="Class",
            name="Foo",
            file_path="src/Foo.java",
            line_start=42,
            line_end=55,
            metadata={"foo": "bar"},
        )
        self.store.upsert_node(
            id="Class:Foo.java:42",
            type="Class",
            name="FooUpdated",
            file_path="src/Foo.java",
            line_start=42,
            line_end=60,
            metadata={"foo": "baz"},
        )

        stats = self.store.stats()
        self.assertEqual(stats["node_count"], 1)

        node = self.store.get_node("Class:Foo.java:42")
        self.assertEqual(node["name"], "FooUpdated")
        self.assertEqual(node["line_end"], 60)
        self.assertEqual(node["metadata"], {"foo": "baz"})

    def test_upsert_edge_idempotent(self):
        """Upserting the same edge twice should not duplicate it."""
        self.store.upsert_node(id="A", type="Class", name="A", file_path="src/A.java")
        self.store.upsert_node(id="B", type="Class", name="B", file_path="src/B.java")

        self.store.upsert_edge(
            source_id="A", target_id="B", relation="calls",
            evidence_path="src/A.java", evidence_line=10,
            metadata={"confidence": 0.9},
        )
        self.store.upsert_edge(
            source_id="A", target_id="B", relation="calls",
            evidence_path="src/A.java", evidence_line=15,
            metadata={"confidence": 0.95},
        )

        stats = self.store.stats()
        self.assertEqual(stats["edge_count"], 1)

        edge = self.store.get_edge("A", "B", "calls")
        self.assertEqual(edge["evidence_line"], 15)
        self.assertEqual(edge["metadata"], {"confidence": 0.95})

    def test_upsert_node_overwrites_all_fields(self):
        """Re-upserting a node should overwrite all fields."""
        self.store.upsert_node(
            id="X", type="Class", name="Original",
            file_path="src/orig.java", line_start=1, line_end=10,
        )
        self.store.upsert_node(
            id="X", type="Method", name="Renamed",
            file_path="src/new.java", line_start=20, line_end=30,
        )

        node = self.store.get_node("X")
        self.assertEqual(node["type"], "Method")
        self.assertEqual(node["name"], "Renamed")
        self.assertEqual(node["file_path"], "src/new.java")
        self.assertEqual(node["line_start"], 20)
        self.assertEqual(node["line_end"], 30)


class TestDeleteCascade(unittest.TestCase):
    """Test that delete_for_file removes all related data."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()
        self.store = GraphStore(self.db_path)

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_delete_for_file_removes_nodes(self):
        """delete_for_file should remove all nodes from the given file."""
        self.store.upsert_node(id="N1", type="Class", name="A", file_path="foo.java")
        self.store.upsert_node(id="N2", type="Method", name="m", file_path="foo.java")
        self.store.upsert_node(id="N3", type="Class", name="B", file_path="bar.java")

        result = self.store.delete_for_file("foo.java")
        self.assertEqual(result["nodes"], 2)

        stats = self.store.stats()
        self.assertEqual(stats["node_count"], 1)
        self.store.get_node("N3")  # should not raise
        self.assertIsNone(self.store.get_node("N1"))

    def test_delete_for_file_removes_edges_from_file(self):
        """delete_for_file should remove edges with evidence_path matching the file."""
        self.store.upsert_node(id="N1", type="Class", name="A", file_path="foo.java")
        self.store.upsert_node(id="N2", type="Class", name="B", file_path="bar.java")
        self.store.upsert_edge(
            source_id="N1", target_id="N2", relation="calls",
            evidence_path="foo.java", evidence_line=5,
        )

        result = self.store.delete_for_file("foo.java")
        self.assertEqual(result["edges"], 1)

        stats = self.store.stats()
        self.assertEqual(stats["edge_count"], 0)

    def test_delete_for_file_cascades_to_edges_on_removed_nodes(self):
        """Edges referencing deleted nodes should also be removed."""
        self.store.upsert_node(id="N1", type="Class", name="A", file_path="foo.java")
        self.store.upsert_node(id="N2", type="Class", name="B", file_path="foo.java")
        self.store.upsert_node(id="N3", type="Class", name="C", file_path="bar.java")

        # N3 calls N1 (N1 is in foo.java, N3 is not)
        self.store.upsert_edge(
            source_id="N3", target_id="N1", relation="calls",
            evidence_path="bar.java", evidence_line=10,
        )

        result = self.store.delete_for_file("foo.java")
        self.assertEqual(result["nodes"], 2)
        self.assertGreaterEqual(result["edges"], 1)  # at least the N3->N1 edge

        stats = self.store.stats()
        self.assertEqual(stats["edge_count"], 0)

    def test_delete_for_file_preserves_other_files(self):
        """delete_for_file should only affect the specified file."""
        self.store.upsert_node(id="N1", type="Class", name="A", file_path="foo.java")
        self.store.upsert_node(id="N2", type="Class", name="B", file_path="bar.java")
        self.store.upsert_node(id="N3", type="Class", name="C", file_path="baz.java")
        self.store.upsert_edge(source_id="N2", target_id="N3", relation="calls")

        result = self.store.delete_for_file("foo.java")
        self.assertEqual(result["nodes"], 1)

        stats = self.store.stats()
        self.assertEqual(stats["node_count"], 2)
        self.assertEqual(stats["edge_count"], 1)
        self.assertIsNotNone(self.store.get_node("N2"))
        self.assertIsNotNone(self.store.get_node("N3"))


class TestCallersCallees(unittest.TestCase):
    """Test callers/callees queries on a 100-node fixture."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()
        self.store = GraphStore(self.db_path)

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _build_100_node_fixture(self):
        """Build a chain of 100 nodes: N0 -> N1 -> N2 -> ... -> N99."""
        for i in range(100):
            self.store.upsert_node(
                id=f"N{i}",
                type="Method" if i % 3 == 0 else "Class",
                name=f"Entity{i}",
                file_path=f"src/Entity{i}.java",
                line_start=i * 10,
                line_end=i * 10 + 5,
            )
        for i in range(99):
            self.store.upsert_edge(
                source_id=f"N{i}", target_id=f"N{i + 1}", relation="calls",
                evidence_path=f"src/Entity{i}.java", evidence_line=1,
            )

    def test_callers_on_100_node_fixture(self):
        """N50 should have exactly 1 caller (N49)."""
        self._build_100_node_fixture()
        callers = self.store.get_callers("N50")
        self.assertEqual(len(callers), 1)
        self.assertEqual(callers[0]["node"]["id"], "N49")

    def test_callees_on_100_node_fixture(self):
        """N50 should have exactly 1 callee (N51)."""
        self._build_100_node_fixture()
        callees = self.store.get_callees("N50")
        self.assertEqual(len(callees), 1)
        self.assertEqual(callees[0]["node"]["id"], "N51")

    def test_callers_callees_endpoints(self):
        """N0 has no callers; N99 has no callees."""
        self._build_100_node_fixture()
        self.assertEqual(len(self.store.get_callers("N0")), 0)
        self.assertEqual(len(self.store.get_callees("N99")), 0)

    def test_neighbors_on_100_node_fixture(self):
        """N50 should have 1 incoming and 1 outgoing neighbor."""
        self._build_100_node_fixture()
        neighbors = self.store.get_neighbors("N50")
        self.assertEqual(len(neighbors["incoming"]), 1)
        self.assertEqual(len(neighbors["outgoing"]), 1)

    def test_stats_on_100_node_fixture(self):
        """Stats should reflect 100 nodes and 99 edges."""
        self._build_100_node_fixture()
        stats = self.store.stats()
        self.assertEqual(stats["node_count"], 100)
        self.assertEqual(stats["edge_count"], 99)
        self.assertIn("Method", stats["type_distribution"])
        self.assertIn("Class", stats["type_distribution"])
        self.assertIn("calls", stats["relation_distribution"])


class TestShortestPath(unittest.TestCase):
    """Test shortest_path query."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()
        self.store = GraphStore(self.db_path)

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_shortest_path_found(self):
        """Shortest path from A to D in A->B->C->D should be [A, B, C, D]."""
        for node_id in ["A", "B", "C", "D"]:
            self.store.upsert_node(id=node_id, type="Class", name=node_id)
        self.store.upsert_edge(source_id="A", target_id="B", relation="calls")
        self.store.upsert_edge(source_id="B", target_id="C", relation="calls")
        self.store.upsert_edge(source_id="C", target_id="D", relation="calls")

        path = self.store.shortest_path("A", "D")
        self.assertEqual(path, ["A", "B", "C", "D"])

    def test_shortest_path_no_path(self):
        """No path between disconnected nodes should return None."""
        self.store.upsert_node(id="X", type="Class", name="X")
        self.store.upsert_node(id="Y", type="Class", name="Y")

        path = self.store.shortest_path("X", "Y")
        self.assertIsNone(path)


class TestPreviewImpact(unittest.TestCase):
    """Test preview_impact analysis."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()
        self.store = GraphStore(self.db_path)

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_preview_impact_chain(self):
        """In a chain A->B->C, preview_impact(B) should show:
        - 1 direct caller (A)
        - 1 direct callee (C)
        - 1 transitive reachable (C)
        - 1 transitive dependent (A)
        """
        for node_id in ["A", "B", "C"]:
            self.store.upsert_node(id=node_id, type="Class", name=node_id)
        self.store.upsert_edge(source_id="A", target_id="B", relation="calls")
        self.store.upsert_edge(source_id="B", target_id="C", relation="calls")

        impact = self.store.preview_impact("B")
        self.assertEqual(impact["direct_callers"], ["A"])
        self.assertEqual(impact["direct_callees"], ["C"])
        self.assertEqual(impact["transitive_reachable"], 1)
        self.assertEqual(impact["transitive_dependents"], 1)
        self.assertFalse(impact["is_hub"])


class TestFindHubModules(unittest.TestCase):
    """Test hub module detection."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()
        self.store = GraphStore(self.db_path)

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_hub_detection(self):
        """A node with 25 connections should be detected as a hub (threshold=20)."""
        self.store.upsert_node(id="HUB", type="Class", name="Hub")
        for i in range(25):
            self.store.upsert_node(id=f"LEAF{i}", type="Method", name=f"leaf{i}")
            self.store.upsert_edge(source_id="HUB", target_id=f"LEAF{i}", relation="calls")

        hubs = self.store.find_hub_modules(threshold=20)
        self.assertEqual(len(hubs), 1)
        self.assertEqual(hubs[0]["id"], "HUB")
        self.assertEqual(hubs[0]["total_degree"], 25)

    def test_no_hubs_below_threshold(self):
        """No node with degree < threshold should appear."""
        self.store.upsert_node(id="SMALL", type="Class", name="Small")
        for i in range(5):
            self.store.upsert_node(id=f"X{i}", type="Method", name=f"x{i}")
            self.store.upsert_edge(source_id="SMALL", target_id=f"X{i}", relation="calls")

        hubs = self.store.find_hub_modules(threshold=20)
        self.assertEqual(len(hubs), 0)


class TestFileState(unittest.TestCase):
    """Test file_state tracking."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()
        self.store = GraphStore(self.db_path)

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_record_and_retrieve_file_state(self):
        self.store.record_file_state("src/Foo.java", "abc123", node_count=5, edge_count=3)
        state = self.store.get_file_state("src/Foo.java")
        self.assertIsNotNone(state)
        self.assertEqual(state["content_hash"], "abc123")
        self.assertEqual(state["node_count"], 5)
        self.assertEqual(state["edge_count"], 3)

    def test_file_state_updated_on_rerecord(self):
        self.store.record_file_state("src/Foo.java", "hash1", node_count=2, edge_count=1)
        self.store.record_file_state("src/Foo.java", "hash2", node_count=4, edge_count=2)
        state = self.store.get_file_state("src/Foo.java")
        self.assertEqual(state["content_hash"], "hash2")
        self.assertEqual(state["node_count"], 4)

    def test_delete_for_file_clears_file_state(self):
        self.store.record_file_state("src/Foo.java", "abc123", node_count=5, edge_count=3)
        self.store.delete_for_file("src/Foo.java")
        state = self.store.get_file_state("src/Foo.java")
        self.assertIsNone(state)

    def test_get_file_state_missing(self):
        self.assertIsNone(self.store.get_file_state("nonexistent.java"))


class TestMetaOperations(unittest.TestCase):
    """Test meta key-value store."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()
        self.store = GraphStore(self.db_path)

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_set_and_get_meta(self):
        self.store.set_meta("version", "1.0.0")
        self.assertEqual(self.store.get_meta("version"), "1.0.0")

    def test_get_meta_missing(self):
        self.assertIsNone(self.store.get_meta("nonexistent"))

    def test_overwrite_meta(self):
        self.store.set_meta("version", "1.0.0")
        self.store.set_meta("version", "2.0.0")
        self.assertEqual(self.store.get_meta("version"), "2.0.0")


class TestPersistence(unittest.TestCase):
    """Test that data persists across DB reopen."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_data_persists_across_reopen(self):
        """Write data, close, reopen, verify data is still there."""
        store1 = GraphStore(self.db_path)
        store1.upsert_node(id="P1", type="Class", name="Persisted", file_path="src/P.java")
        store1.upsert_edge(source_id="P1", target_id="P1", relation="calls")
        store1.set_meta("version", "1.0.0")
        store1.close()

        store2 = GraphStore(self.db_path)
        self.assertEqual(store2.stats()["node_count"], 1)
        self.assertEqual(store2.stats()["edge_count"], 1)
        self.assertEqual(store2.get_meta("version"), "1.0.0")
        node = store2.get_node("P1")
        self.assertEqual(node["name"], "Persisted")
        store2.close()


class TestContextManager(unittest.TestCase):
    """Test context manager lifecycle."""

    def test_context_manager(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        db_path = tmp.name
        tmp.close()
        try:
            with GraphStore(db_path) as store:
                store.upsert_node(id="CM1", type="Class", name="CM")
                self.assertEqual(store.stats()["node_count"], 1)
            # After context exit, connection should be closed
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)


class TestListNodes(unittest.TestCase):
    """Test list_nodes with filters."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()
        self.store = GraphStore(self.db_path)

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_list_all_nodes(self):
        self.store.upsert_node(id="L1", type="Class", name="A", file_path="src/A.java")
        self.store.upsert_node(id="L2", type="Method", name="m", file_path="src/A.java")
        self.store.upsert_node(id="L3", type="Class", name="B", file_path="src/B.java")

        nodes = self.store.list_nodes()
        self.assertEqual(len(nodes), 3)

    def test_list_nodes_by_type(self):
        self.store.upsert_node(id="L1", type="Class", name="A", file_path="src/A.java")
        self.store.upsert_node(id="L2", type="Method", name="m", file_path="src/A.java")

        nodes = self.store.list_nodes(node_type="Class")
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["type"], "Class")

    def test_list_nodes_by_file(self):
        self.store.upsert_node(id="L1", type="Class", name="A", file_path="src/A.java")
        self.store.upsert_node(id="L2", type="Method", name="m", file_path="src/B.java")

        nodes = self.store.list_nodes(file_path="src/A.java")
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["file_path"], "src/A.java")


class TestAcceptanceCriteria(unittest.TestCase):
    """Direct acceptance criteria from the task spec."""

    def test_acceptance_cli_command(self):
        """python -c "from src.graph.store import GraphStore;
        s = GraphStore('test.db'); s.upsert_node(id='X', type='Class', name='X');
        print(s.stats())" works."""
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        db_path = tmp.name
        tmp.close()
        try:
            from src.graph.store import GraphStore
            s = GraphStore(db_path)
            s.upsert_node(id="X", type="Class", name="X")
            result = s.stats()
            self.assertEqual(result["node_count"], 1)
            self.assertEqual(result["type_distribution"]["Class"], 1)
            s.close()
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)

    def test_delete_for_file_removes_all(self):
        """delete_for_file('foo.java') removes all nodes whose file_path == 'foo.java'
        AND any edges referencing them."""
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        db_path = tmp.name
        tmp.close()
        try:
            store = GraphStore(db_path)
            store.upsert_node(id="N1", type="Class", name="A", file_path="foo.java")
            store.upsert_node(id="N2", type="Method", name="m", file_path="foo.java")
            store.upsert_node(id="N3", type="Class", name="B", file_path="bar.java")
            store.upsert_edge(source_id="N1", target_id="N2", relation="contains")
            store.upsert_edge(source_id="N3", target_id="N1", relation="calls")

            result = store.delete_for_file("foo.java")
            self.assertEqual(result["nodes"], 2)
            self.assertGreaterEqual(result["edges"], 2)  # contains + calls

            self.assertEqual(store.stats()["node_count"], 1)
            self.assertEqual(store.stats()["edge_count"], 0)
            store.close()
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)


class TestMetadataJSON(unittest.TestCase):
    """Test that metadata is stored as JSON, not pickle."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()
        self.store = GraphStore(self.db_path)

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_metadata_serialized_as_json(self):
        """Metadata should be stored as a JSON string in the database."""
        meta = {"confidence": 0.95, "tags": ["important", "reviewed"], "nested": {"key": "value"}}
        self.store.upsert_node(
            id="JSON1", type="Class", name="JsonTest",
            file_path="src/Json.java", metadata=meta,
        )

        # Read raw from DB to verify JSON storage
        row = self.store.conn.execute(
            "SELECT metadata FROM nodes WHERE id = ?", ("JSON1",)
        ).fetchone()
        parsed = json.loads(row["metadata"])
        self.assertEqual(parsed, meta)

    def test_metadata_roundtrip(self):
        """Metadata should survive a full upsert -> get_node roundtrip."""
        meta = {"confidence": 0.7, "source": "ast", "flags": [1, 2, 3]}
        self.store.upsert_node(id="RT1", type="Method", name="roundTrip", metadata=meta)
        node = self.store.get_node("RT1")
        self.assertEqual(node["metadata"], meta)

    def test_none_metadata_becomes_empty_dict(self):
        self.store.upsert_node(id="NM1", type="Class", name="NoMeta")
        node = self.store.get_node("NM1")
        self.assertEqual(node["metadata"], {})


if __name__ == "__main__":
    unittest.main()
