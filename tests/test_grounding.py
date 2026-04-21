"""Unit tests for grounding utilities.

Tests the core grounding functions:
- prepend_grounding
- contains_abstain
- strip_abstain_blocks
- load_noise_filter
"""

from typing import Dict, Any
from src.rag.grounding import (
    G_VERSION,
    ABSTAIN_TOKEN,
    GROUNDING_INSTRUCTION,
    prepend_grounding,
    contains_abstain,
    strip_abstain_blocks,
    DEFAULT_NOISE_FILTER,
    load_noise_filter,
    GROUNDING_VERSION,
    NOISE_FILTER_TERMS,
)


class TestPrependGrounding:
    """Test prepend_grounding function."""

    def test_prepends_grounding_instruction(self):
        """Test that grounding instruction is prepended to system prompt."""
        base_prompt = "You are a helpful assistant"
        result = prepend_grounding(base_prompt)
        
        assert GROUNDING_INSTRUCTION in result
        assert base_prompt in result
        assert "---" in result

    def test_preserves_original_prompt(self):
        """Test that original prompt is preserved after prepending."""
        original = "Original system prompt"
        result = prepend_grounding(original)
        
        assert original in result


class TestContainsAbstain:
    """Test contains_abstain function."""

    def test_returns_true_when_token_present(self):
        """Test that function returns True when abstain token is present."""
        text = f"Some text {ABSTAIN_TOKEN} more text"
        assert contains_abstain(text) is True

    def test_returns_false_when_token_absent(self):
        """Test that function returns False when abstain token is absent."""
        text = "This is a normal text without the token"
        assert contains_abstain(text) is False

    def test_case_sensitive(self):
        """Test that token detection is case-sensitive."""
        text = "This contains [insufficient_evidence] but not the exact token"
        assert contains_abstain(text) is False


class TestStripAbstainBlocks:
    """Test strip_abstain_blocks function."""

    def test_removes_lines_with_only_token(self):
        """Test that lines containing only the abstain token are removed."""
        text = f"Line 1\n{ABSTAIN_TOKEN}\nLine 3"
        result = strip_abstain_blocks(text)
        
        assert ABSTAIN_TOKEN not in result
        assert "Line 1" in result
        assert "Line 3" in result

    def test_replaces_inline_token_with_unknown(self):
        """Test that inline abstain tokens are replaced with '(unknown)'."""
        text = f"This is a sentence with {ABSTAIN_TOKEN} embedded"
        result = strip_abstain_blocks(text)
        
        assert ABSTAIN_TOKEN not in result
        assert "(unknown)" in result
        assert "embedded" in result

    def test_handles_multiple_occurrences(self):
        """Test handling of multiple abstain markers in text."""
        text = f"First {ABSTAIN_TOKEN}\nSecond line\n{ABSTAIN_TOKEN} in middle"
        result = strip_abstain_blocks(text)
        
        assert result.count(ABSTAIN_TOKEN) == 0
        assert "(unknown)" in result
        assert "First" in result
        assert "Second line" in result


class TestLoadNoiseFilter:
    """Test load_noise_filter function."""

    def test_returns_frozenset(self):
        """Test that load_noise_filter returns a frozenset."""
        config = {"noise_filter": {"terms": []}}
        result = load_noise_filter(config)
        
        assert isinstance(result, frozenset)

    def test_includes_default_terms(self):
        """Test that default terms are included in the result."""
        config = {"noise_filter": {"terms": []}}
        result = load_noise_filter(config)
        
        for term in DEFAULT_NOISE_FILTER:
            assert term in result

    def test_includes_user_terms(self):
        """Test that user-provided terms are included."""
        config = {"noise_filter": {"terms": ["CustomTerm1", "CustomTerm2"]}}
        result = load_noise_filter(config)
        
        assert "CustomTerm1" in result
        assert "CustomTerm2" in result

    def test_merges_terms_without_duplicates(self):
        """Test that default and user terms are merged without duplicates."""
        config = {"noise_filter": {"terms": ["Spring", "NewTerm"]}}
        result = load_noise_filter(config)
        
        # Should have default terms + NewTerm (Spring already in defaults)
        assert "Spring" in result
        assert "NewTerm" in result
        assert len(result) > len(DEFAULT_NOISE_FILTER)

    def test_handles_empty_config(self):
        """Test that function handles empty config gracefully."""
        result = load_noise_filter({})
        
        # Should still return default noise filter
        for term in DEFAULT_NOISE_FILTER:
            assert term in result

    def test_handles_none_config(self):
        """Test that function handles None config gracefully."""
        result = load_noise_filter(None)  # type: ignore
        
        # Should still return default noise filter
        for term in DEFAULT_NOISE_FILTER:
            assert term in result


class TestConstants:
    """Test module constants."""

    def test_g_version_is_1_0_0(self):
        """Test that G_VERSION is set to 1.0.0."""
        assert G_VERSION == "1.0.0"

    def test_abstain_token_is_correct(self):
        """Test that ABSTAIN_TOKEN has the correct value."""
        assert ABSTAIN_TOKEN == "[INSUFFICIENT_EVIDENCE]"

    def test_grounding_instruction_not_empty(self):
        """Test that GROUNDING_INSTRUCTION is not empty."""
        assert GROUNDING_INSTRUCTION.strip()
        assert len(GROUNDING_INSTRUCTION) > 100

    def test_grounding_version_matches_g_version(self):
        """Test that GROUNDING_VERSION matches G_VERSION."""
        assert GROUNDING_VERSION == G_VERSION

    def test_noise_filter_terms_is_frozenset(self):
        """Test that NOISE_FILTER_TERMS is a frozenset."""
        assert isinstance(NOISE_FILTER_TERMS, frozenset)

    def test_default_noise_filter_has_expected_terms(self):
        """Test that DEFAULT_NOISE_FILTER contains expected framework terms."""
        expected_terms = {"Spring", "JPA", "Hibernate", "Repository", "Controller", "Service"}
        assert expected_terms.issubset(DEFAULT_NOISE_FILTER)
