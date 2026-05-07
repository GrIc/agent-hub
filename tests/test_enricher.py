"""Unit tests for src/graph/enricher.py — language-agnostic LLM enrichment."""

import json
import pytest
from unittest.mock import Mock, MagicMock

from src.graph.enricher import (
    ALLOWED_INTENTS,
    enrich_node,
    enrich_all,
    build_neighborhood_text,
    ABSTAIN_TOKEN,
)
from src.graph.store import GraphStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_llm():
    """Mock LLM client with chat.completions.create returning controlled responses."""
    client = Mock()
    client.chat = Mock()
    client.chat.completions = Mock()
    return client


@pytest.fixture
def store(tmp_path):
    """In-memory GraphStore for testing."""
    db_path = str(tmp_path / ".graphdb" / "test_enricher.sqlite")
    store = GraphStore(db_path=db_path)
    yield store
    store.close()


# ---------------------------------------------------------------------------
# Tests: enrich_node
# ---------------------------------------------------------------------------


def test_enrich_node_requires_class_or_service_by_default(store, mock_llm):
    """Default behavior skips Method and Field nodes."""
    # Create a Method node
    store.upsert_node(
        id="Method:foo.py:10",
        type="Method",
        name="foo",
        file_path="foo.py",
        line_start=10,
        metadata={"source_hash": "abc123"},
    )
    
    result = enrich_node(store, "Method:foo.py:10", mock_llm, "")
    assert result["description"] == ""
    assert result["intent"] == ""
    assert result["confidence"] == 0.0


def test_enrich_node_accepts_custom_only_types(store, mock_llm):
    """Custom only_types allows enriching Method nodes."""
    store.upsert_node(
        id="Method:bar.py:20",
        type="Method",
        name="bar",
        file_path="bar.py",
        line_start=20,
        metadata={"source_hash": "def456"},
    )
    
    result = enrich_node(
        store,
        "Method:bar.py:20",
        mock_llm,
        "",
        only_types={"Method"},
    )
    # Should attempt enrichment (though mocked LLM will abstain)
    assert "description" in result
    assert "intent" in result
    assert "confidence" in result


def test_enrich_node_abstains_on_missing_node(store, mock_llm):
    """Returns abstain when node not found."""
    result = enrich_node(store, "Missing:node:999", mock_llm, "")
    assert result["description"] == ABSTAIN_TOKEN
    assert result["intent"] == "unknown"
    assert result["confidence"] == 0.0


def test_enrich_node_validates_intent_against_allowed_set(store, mock_llm):
    """LLM-provided intent outside allowed set is replaced with 'unknown'."""
    # Mock LLM returning invalid intent
    mock_llm.chat.completions.create.return_value.choices[0].message.content = json.dumps({
        "description": "Some description",
        "intent": "invalid_intent_xyz",
        "confidence": 0.8,
    })
    
    store.upsert_node(
        id="Class:MyClass.java:42",
        type="Class",
        name="MyClass",
        file_path="MyClass.java",
        line_start=42,
        metadata={"source_hash": "hash1"},
    )
    
    result = enrich_node(store, "Class:MyClass.java:42", mock_llm, "")
    assert result["intent"] == "unknown"
    assert result["confidence"] == 0.8


def test_enrich_node_caps_description_length(store, mock_llm):
    """Description longer than 200 chars is truncated."""
    long_desc = "A" * 250
    mock_llm.chat.completions.create.return_value.choices[0].message.content = json.dumps({
        "description": long_desc,
        "intent": "utility",
        "confidence": 0.9,
    })
    
    store.upsert_node(
        id="Class:LongDesc.java:1",
        type="Class",
        name="LongDesc",
        file_path="LongDesc.java",
        line_start=1,
        metadata={"source_hash": "hash2"},
    )
    
    result = enrich_node(store, "Class:LongDesc.java:1", mock_llm, "")
    assert len(result["description"]) <= 200
    assert result["description"].endswith("...")


def test_enrich_node_returns_valid_json_structure(store, mock_llm):
    """Response always has required fields: description, intent, confidence."""
    mock_llm.chat.completions.create.return_value.choices[0].message.content = json.dumps({
        "description": "A useful helper class.",
        "intent": "utility",
        "confidence": 0.95,
    })
    
    store.upsert_node(
        id="Class:Helper.java:5",
        type="Class",
        name="Helper",
        file_path="Helper.java",
        line_start=5,
        metadata={"source_hash": "hash3"},
    )
    
    result = enrich_node(store, "Class:Helper.java:5", mock_llm, "")
    assert "description" in result
    assert "intent" in result
    assert "confidence" in result
    assert isinstance(result["description"], str)
    assert isinstance(result["intent"], str)
    assert isinstance(result["confidence"], (int, float))


def test_enrich_node_handles_invalid_json_from_llm(store, mock_llm):
    """Invalid JSON from LLM triggers abstain."""
    mock_llm.chat.completions.create.return_value.choices[0].message.content = "Not JSON"
    
    store.upsert_node(
        id="Class:BadJson.java:10",
        type="Class",
        name="BadJson",
        file_path="BadJson.java",
        line_start=10,
        metadata={"source_hash": "hash4"},
    )
    
    result = enrich_node(store, "Class:BadJson.java:10", mock_llm, "")
    assert result["description"] == ABSTAIN_TOKEN
    assert result["confidence"] == 0.0


def test_enrich_node_confidence_clamped(store, mock_llm):
    """Confidence is clamped to [0.0, 1.0]."""
    mock_llm.chat.completions.create.return_value.choices[0].message.content = json.dumps({
        "description": "A class",
        "intent": "utility",
        "confidence": 1.5,
    })
    
    store.upsert_node(
        id="Class:Clamp.java:1",
        type="Class",
        name="Clamp",
        file_path="Clamp.java",
        line_start=1,
        metadata={"source_hash": "hash5"},
    )
    
    result = enrich_node(store, "Class:Clamp.java:1", mock_llm, "")
    assert result["confidence"] == 1.0

    mock_llm.chat.completions.create.return_value.choices[0].message.content = json.dumps({
        "description": "A class",
        "intent": "utility",
        "confidence": -0.5,
    })
    
    result = enrich_node(store, "Class:Clamp.java:1", mock_llm, "")
    assert result["confidence"] == 0.0


# ---------------------------------------------------------------------------
# Tests: enrich_all
# ---------------------------------------------------------------------------


def test_enrich_all_defaults_to_class_and_service(store, mock_llm):
    """By default, only Class and Service nodes are enriched."""
    # Create nodes of different types
    for node_type, name in [("Class", "C1"), ("Service", "S1"), ("Method", "M1"), ("Field", "F1")]:
        store.upsert_node(
            id=f"{node_type}:{name}.py:1",
            type=node_type,
            name=name,
            file_path=f"{name}.py",
            line_start=1,
            metadata={"source_hash": f"hash_{node_type}"},
        )
    
    # Mock LLM responses
    def mock_create(*args, **kwargs):
        msg = Mock()
        msg.choices[0].message.content = json.dumps({
            "description": f"Description for {args[0]['messages'][1]['content'].split('name: ')[1].split('\\n')[0]}",
            "intent": "utility",
            "confidence": 0.8,
        })
        return msg
    
    mock_llm.chat.completions.create = mock_create
    
    stats = enrich_all(store, mock_llm)
    assert stats["total"] == 4
    assert stats["enriched"] == 2  # Class and Service only
    assert stats["skipped"] == 0


def test_enrich_all_respects_only_types(store, mock_llm):
    """Custom only_types set is respected."""
    store.upsert_node(
        id="Method:M1.py:1",
        type="Method",
        name="M1",
        file_path="M1.py",
        line_start=1,
        metadata={"source_hash": "hash_m1"},
    )
    
    def mock_create(*args, **kwargs):
        msg = Mock()
        msg.choices[0].message.content = json.dumps({
            "description": "A method",
            "intent": "utility",
            "confidence": 0.7,
        })
        return msg
    
    mock_llm.chat.completions.create = mock_create
    
    stats = enrich_all(store, mock_llm, only_types={"Method"})
    assert stats["total"] == 1
    assert stats["enriched"] == 1


def test_enrich_all_incremental_skipping(store, mock_llm):
    """Nodes with enrichment_version=2.0 and unchanged source_hash are skipped."""
    # First enrichment
    store.upsert_node(
        id="Class:C1.java:1",
        type="Class",
        name="C1",
        file_path="C1.java",
        line_start=1,
        metadata={
            "source_hash": "hash_c1",
            "enrichment_version": "2.0",
            "description": "Old description",
            "intent": "old_intent",
            "enrichment_confidence": 0.5,
        },
    )
    
    def mock_create(*args, **kwargs):
        raise AssertionError("Should not call LLM for already enriched node")
    
    mock_llm.chat.completions.create = mock_create
    
    stats = enrich_all(store, mock_llm)
    assert stats["total"] == 1
    assert stats["enriched"] == 0
    assert stats["skipped"] == 1


def test_enrich_all_updates_metadata(store, mock_llm):
    """Enrichment updates node metadata with new fields."""
    store.upsert_node(
        id="Class:UpdateMe.java:1",
        type="Class",
        name="UpdateMe",
        file_path="UpdateMe.java",
        line_start=1,
        metadata={"source_hash": "hash_update", "other": "data"},
    )
    
    mock_llm.chat.completions.create.return_value.choices[0].message.content = json.dumps({
        "description": "Updated description",
        "intent": "service",
        "confidence": 0.9,
    })
    
    enrich_all(store, mock_llm)
    
    node = store.get_node("Class:UpdateMe.java:1")
    meta = node["metadata"]
    assert meta["enrichment_version"] == "2.0"
    assert meta["description"] == "Updated description"
    assert meta["intent"] == "service"
    assert meta["enrichment_confidence"] == 0.9
    assert meta["other"] == "data"  # Preserved


def test_enrich_all_abstain_updates_metadata(store, mock_llm):
    """Even on abstain, metadata fields are set (with abstain token)."""
    store.upsert_node(
        id="Class:Abstain.java:1",
        type="Class",
        name="Abstain",
        file_path="Abstain.java",
        line_start=1,
        metadata={"source_hash": "hash_abstain"},
    )
    
    mock_llm.chat.completions.create.return_value.choices[0].message.content = json.dumps({
        "description": ABSTAIN_TOKEN,
        "intent": "unknown",
        "confidence": 0.0,
    })
    
    enrich_all(store, mock_llm)
    
    node = store.get_node("Class:Abstain.java:1")
    meta = node["metadata"]
    assert meta["enrichment_version"] == "2.0"
    assert meta["description"] == ABSTAIN_TOKEN
    assert meta["intent"] == "unknown"
    assert meta["enrichment_confidence"] == 0.0


# ---------------------------------------------------------------------------
# Tests: build_neighborhood_text
# ---------------------------------------------------------------------------


def test_build_neighborhood_text_includes_callers_and_callees(store):
    """Neighborhood text includes caller and callee information."""
    # Create caller node
    store.upsert_node(
        id="Class:Caller.java:10",
        type="Class",
        name="Caller",
        file_path="Caller.java",
        line_start=10,
    )
    # Create callee node
    store.upsert_node(
        id="Class:Callee.java:20",
        type="Class",
        name="Callee",
        file_path="Callee.java",
        line_start=20,
    )
    # Create central node
    store.upsert_node(
        id="Class:Central.java:5",
        type="Class",
        name="Central",
        file_path="Central.java",
        line_start=5,
    )
    # Create calls edges
    store.upsert_edge(
        source_id="Class:Caller.java:10",
        target_id="Class:Central.java:5",
        relation="calls",
    )
    store.upsert_edge(
        source_id="Class:Central.java:5",
        target_id="Class:Callee.java:20",
        relation="calls",
    )
    
    text = build_neighborhood_text(store, "Class:Central.java:5")
    assert "Caller" in text
    assert "Callee" in text
    assert "Callers:" in text
    assert "Callees:" in text


def test_build_neighborhood_text_handles_missing_node(store):
    """Returns message when node not found."""
    text = build_neighborhood_text(store, "Missing:node:999")
    assert "Node not found" in text


def test_build_neighborhood_text_includes_metadata(store):
    """Includes metadata in neighborhood text."""
    store.upsert_node(
        id="Class:Meta.java:1",
        type="Class",
        name="Meta",
        file_path="Meta.java",
        line_start=1,
        metadata={"key1": "val1", "key2": "val2"},
    )
    
    text = build_neighborhood_text(store, "Class:Meta.java:1")
    assert "Metadata:" in text
    assert "key1: val1" in text
    assert "key2: val2" in text


# ---------------------------------------------------------------------------
# Tests: ALLOWED_INTENTS
# ---------------------------------------------------------------------------


def test_allowed_intents_is_frozenset():
    """ALLOWED_INTENTS is a frozenset for immutability."""
    assert isinstance(ALLOWED_INTENTS, frozenset)


def test_allowed_intents_contains_expected_values():
    """ALLOWED_INTENTS contains the expected intent taxonomy."""
    expected = {
        "data", "logic", "io", "controller", "service", "repository",
        "utility", "config", "test", "entrypoint", "unknown",
    }
    assert ALLOWED_INTENTS == expected
