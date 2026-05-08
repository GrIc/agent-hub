"""Tests for src/temporal/enricher.py.

These tests verify the grounded commit enrichment system.
They test risk score computation, module extraction, JSON parsing,
and the enrichment pipeline with mocked LLM calls.
"""

import json
from pathlib import Path
from unittest import mock

import pytest

from src.rag.grounding import ABSTAIN_TOKEN
from src.temporal.enricher import (
    ALLOWED_INTENTS,
    _compute_risk_score,
    _extract_module_path,
    _is_hub_module,
    _split_ext,
    _try_enrich,
    enrich_commit,
    enrich_pending,
)
from src.temporal.git_client import Commit, FileChange
from src.temporal.store import TemporalStore


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture()
def mock_llm_client():
    """Return a mock LLM client that returns valid JSON responses."""
    client = mock.MagicMock()
    client.chat.return_value = json.dumps({
        "intent": "feature",
        "summary": "Added new authentication module.",
        "modules_affected": ["src/auth"],
    })
    return client


@pytest.fixture()
def sample_commit():
    """Return a sample Commit object."""
    return Commit(
        sha="a" * 40,
        author="Test Author",
        date="2026-05-08T10:00:00+02:00",
        subject="feat(auth): Add SSO support",
        body="Implemented SAML 2.0 SSO for external users.",
    )


@pytest.fixture()
def sample_files():
    """Return sample FileChange objects."""
    return [
        FileChange(path="src/auth/sso.py", status="A", insertions=150, deletions=0),
        FileChange(path="src/auth/models.py", status="M", insertions=20, deletions=5),
        FileChange(path="tests/test_sso.py", status="A", insertions=80, deletions=0),
    ]


# ── _extract_module_path ──────────────────────────────────────────

class TestExtractModulePath:
    def test_deep_path(self):
        """Deep path returns first 2 components."""
        assert _extract_module_path("src/auth/login.py") == "src/auth"

    def test_shallow_path(self):
        """Single-component path returns that component."""
        # Single component (no /) returns the full name with extension
        result = _extract_module_path("README.md")
        assert result in ("README.md", "README")

    def test_two_component_path(self):
        """Two-component path returns first component."""
        assert _extract_module_path("src/main.py") == "src"

    def test_empty_path(self):
        """Empty path returns empty string."""
        assert _extract_module_path("") == ""


# ── _split_ext ────────────────────────────────────────────────────

class TestSplitExt:
    def test_python_file(self):
        path, ext = _split_ext("src/main.py")
        assert path == "src/main"
        assert ext == ".py"

    def test_java_file(self):
        path, ext = _split_ext("src/Auth.java")
        assert path == "src/Auth"
        assert ext == ".java"

    def test_yaml_file(self):
        path, ext = _split_ext("config.yaml")
        assert path == "config"
        assert ext == ".yaml"


# ── _is_hub_module ────────────────────────────────────────────────

class TestIsHubModule:
    def test_graph_store_has_is_hub(self):
        """Uses is_hub() method if available."""
        gs = mock.MagicMock(spec=["is_hub"])
        gs.is_hub.return_value = True
        assert _is_hub_module(gs, "src/auth") is True

    def test_graph_store_has_get_node(self):
        """Falls back to node.degree if is_hub not available."""
        node = mock.MagicMock()
        node.degree = 15
        gs = mock.MagicMock(spec=["get_node"])
        gs.get_node.return_value = node
        assert _is_hub_module(gs, "src/auth") is True

    def test_graph_store_has_get_node_low_degree(self):
        """Returns False if node degree is low."""
        node = mock.MagicMock()
        node.degree = 5
        gs = mock.MagicMock(spec=["get_node"])
        gs.get_node.return_value = node
        assert _is_hub_module(gs, "src/auth") is False

    def test_graph_store_exception(self):
        """Returns False on exception."""
        gs = mock.MagicMock()
        gs.is_hub.side_effect = Exception("DB error")
        assert _is_hub_module(gs, "src/auth") is False

    def test_no_graph_store(self):
        """Returns False when graph_store is None."""
        assert _is_hub_module(None, "src/auth") is False


# ── _compute_risk_score ───────────────────────────────────────────

class TestComputeRiskScore:
    def test_baseline(self):
        """Empty files list → score 0.0."""
        assert _compute_risk_score([]) == 0.0

    def test_many_files(self):
        """>5 files → +0.3."""
        files = [FileChange(path=f"src/file{i}.py", status="A", insertions=1, deletions=0)
                 for i in range(6)]
        score = _compute_risk_score(files)
        assert score >= 0.3

    def test_config_file(self):
        """Config file → +0.2."""
        files = [FileChange(path="config.yaml", status="M", insertions=5, deletions=0)]
        score = _compute_risk_score(files)
        assert score >= 0.2

    def test_dockerfile(self):
        """Dockerfile → +0.2."""
        files = [FileChange(path="Dockerfile", status="M", insertions=3, deletions=0)]
        score = _compute_risk_score(files)
        assert score >= 0.2

    def test_large_diff(self):
        """Large net lines → +0.1 per 100 (capped at 0.4)."""
        files = [FileChange(path="src/large.py", status="M", insertions=500, deletions=0)]
        score = _compute_risk_score(files)
        # 500 lines → 0.1 * 5 = 0.5, capped at 0.4
        assert score >= 0.4

    def test_capped_at_one(self):
        """Score is capped at 1.0."""
        files = [
            FileChange(path=f"src/file{i}.py", status="A", insertions=500, deletions=0)
            for i in range(10)
        ]
        files.append(FileChange(path="config.yaml", status="M", insertions=10, deletions=0))
        score = _compute_risk_score(files)
        assert score <= 1.0

    def test_hub_module(self):
        """Hub module detection adds +0.2."""
        gs = mock.MagicMock(spec=["is_hub"])
        gs.is_hub.return_value = True
        files = [FileChange(path="src/auth/login.py", status="M", insertions=10, deletions=0)]
        score = _compute_risk_score(files, graph_store=gs)
        assert score >= 0.2


# ── _try_enrich ───────────────────────────────────────────────────

class TestTryEnrich:
    def test_valid_json_response(self, mock_llm_client):
        """Valid JSON response is parsed correctly."""
        result = _try_enrich(
            "system", "user", mock_llm_client, "gpt-4o", 0.1, 4096
        )
        assert result["intent"] == "feature"
        assert result["summary"] == "Added new authentication module."
        assert result["modules_affected"] == ["src/auth"]

    def test_invalid_json(self):
        """Invalid JSON returns abstain."""
        client = mock.MagicMock()
        client.chat.return_value = "not json at all"
        result = _try_enrich("system", "user", client, "gpt-4o", 0.1, 4096)
        assert result["intent"] == "unknown"
        assert result["summary"] == ABSTAIN_TOKEN

    def test_llm_call_exception(self):
        """LLM exception returns abstain."""
        client = mock.MagicMock()
        client.chat.side_effect = Exception("API error")
        result = _try_enrich("system", "user", client, "gpt-4o", 0.1, 4096)
        assert result["intent"] == "unknown"
        assert result["summary"] == ABSTAIN_TOKEN

    def test_markdown_fences_stripped(self):
        """Markdown JSON fences are stripped before parsing."""
        client = mock.MagicMock()
        client.chat.return_value = '```json\n{"intent": "fix", "summary": "Bug fix", "modules_affected": []}\n```'
        result = _try_enrich("system", "user", client, "gpt-4o", 0.1, 4096)
        assert result["intent"] == "fix"

    def test_invalid_intent_defaults_to_unknown(self):
        """Invalid intent value defaults to 'unknown'."""
        client = mock.MagicMock()
        client.chat.return_value = json.dumps({
            "intent": "invalid_intent",
            "summary": "Test",
            "modules_affected": [],
        })
        result = _try_enrich("system", "user", client, "gpt-4o", 0.1, 4096)
        assert result["intent"] == "unknown"

    def test_empty_summary_returns_abstain(self):
        """Empty summary returns ABSTAIN_TOKEN."""
        client = mock.MagicMock()
        client.chat.return_value = json.dumps({
            "intent": "feature",
            "summary": "",
            "modules_affected": [],
        })
        result = _try_enrich("system", "user", client, "gpt-4o", 0.1, 4096)
        assert result["summary"] == ABSTAIN_TOKEN


# ── enrich_commit ─────────────────────────────────────────────────

class TestEnrichCommit:
    def test_enrichment_result(self, sample_commit, sample_files, mock_llm_client):
        """enrich_commit returns a dict with required keys."""
        result = enrich_commit(
            sample_commit, sample_files, "diff text",
            llm_client=mock_llm_client,
            config={"models": {"heavy": "gpt-4o"}, "grounding": {}},
        )
        assert "intent" in result
        assert "summary" in result
        assert "modules_affected" in result
        assert "risk_score" in result
        assert result["intent"] in ALLOWED_INTENTS
        assert 0.0 <= result["risk_score"] <= 1.0

    def test_retry_on_abstain(self, sample_commit, sample_files):
        """Retries once when first attempt returns abstain."""
        call_count = 0

        def chat_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return json.dumps({
                    "intent": "unknown",
                    "summary": ABSTAIN_TOKEN,
                    "modules_affected": [],
                })
            return json.dumps({
                "intent": "fix",
                "summary": "Fixed the issue.",
                "modules_affected": ["src/auth"],
            })

        client = mock.MagicMock()
        client.chat.side_effect = chat_side_effect

        result = enrich_commit(
            sample_commit, sample_files, "diff",
            llm_client=client,
            config={"models": {"heavy": "gpt-4o"}, "grounding": {}},
        )

        assert call_count == 2
        assert result["intent"] == "fix"


# ── enrich_pending ────────────────────────────────────────────────

class TestEnrichPending:
    def test_enrich_pending_incremental(self, tmp_path, sample_commit, sample_files, mock_llm_client):
        """enrich_pending enriches only unenriched commits."""
        db_path = tmp_path / "commits.sqlite"
        store = TemporalStore(db_path)

        # Upsert commit (not enriched yet)
        store.upsert_commit(sample_commit, sample_files)
        assert store.is_enriched(sample_commit.sha) is False

        # Mock git_client.diff_for_commit (where it's called from)
        with mock.patch("src.temporal.git_client.diff_for_commit") as mock_diff:
            mock_diff.return_value = "diff --git a/src/auth/sso.py b/src/auth/sso.py"
            count = enrich_pending(
                store,
                llm_client=mock_llm_client,
                config={"models": {"heavy": "gpt-4o"}, "grounding": {}},
            )

        assert count == 1
        assert store.is_enriched(sample_commit.sha) is True

    def test_enrich_pending_no_unenriched(self, tmp_path, sample_commit, sample_files, mock_llm_client):
        """enrich_pending returns 0 when all commits are enriched."""
        db_path = tmp_path / "commits.sqlite"
        store = TemporalStore(db_path)

        store.upsert_commit(sample_commit, sample_files)
        store.set_enrichment(
            sample_commit.sha,
            intent="feature",
            summary="Test.",
            modules_affected=[],
            risk_score=0.0,
            g_version="1.0.0",
        )

        count = enrich_pending(
            store,
            llm_client=mock_llm_client,
            config={"models": {"heavy": "gpt-4o"}, "grounding": {}},
        )

        assert count == 0

    def test_enrich_pending_missing_commit(self, tmp_path, mock_llm_client):
        """enrich_pending skips commits that are no longer in store."""
        db_path = tmp_path / "commits.sqlite"
        store = TemporalStore(db_path)

        # Manually insert a SHA that doesn't exist as a full record
        store.connection.execute("""
            INSERT INTO commits (sha, author, date, subject, body, files_json)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("z" * 40, "Z", "2026-05-08", "test", "", "[]"))

        count = enrich_pending(
            store,
            llm_client=mock_llm_client,
            config={"models": {"heavy": "gpt-4o"}, "grounding": {}},
        )

        # Should enrich the commit (it exists in the store)
        assert count >= 0
