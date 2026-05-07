"""Tests for src/graph/parsers.py — the ONLY language-aware file in src/graph/."""

from functools import wraps

import pytest

from tree_sitter import Language, Parser

from src.graph.parsers import (
    _LANG_LOADERS,
    get_parser,
    supported_languages,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Languages that are actually installed in the test environment.
INSTALLED_LANGUAGES = {"java", "python"}


def _skip_if_not_installed(lang):
    """Return True if the language package is not installed."""
    return lang not in INSTALLED_LANGUAGES


# ---------------------------------------------------------------------------
# Test: each supported language loads without error
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lang", _LANG_LOADERS.keys())
def test_each_supported_language_in_loader_dict(lang):
    """Every key in _LANG_LOADERS maps to a callable."""
    assert isinstance(_LANG_LOADERS[lang], type(lambda: None))


@pytest.mark.parametrize("lang", INSTALLED_LANGUAGES)
def test_each_supported_language_loads(lang):
    """Each installed language returns a valid (Parser, Language) pair."""
    result = get_parser(lang)
    assert result is not None
    parser, language = result
    assert isinstance(parser, Parser)
    assert isinstance(language, Language)


# ---------------------------------------------------------------------------
# Test: get_parser returns correct types
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lang", INSTALLED_LANGUAGES)
def test_get_parser_returns_correct_types(lang):
    """get_parser returns (Parser, Language) tuple for installed languages."""
    result = get_parser(lang)
    assert result is not None
    parser, language = result
    assert isinstance(parser, Parser)
    assert isinstance(language, Language)
    # Parser should be able to parse bytes
    tree = parser.parse(b"x = 1")
    assert tree is not None


def test_get_parser_returns_none_for_unsupported_language():
    """get_parser returns None for languages not in _LANG_LOADERS."""
    result = get_parser("rust")
    assert result is None


def test_get_parser_returns_none_for_missing_package():
    """get_parser returns None when the language is known but package missing."""
    # javascript, typescript, go are in _LANG_LOADERS but not installed
    for lang in ("javascript", "typescript", "go"):
        if _skip_if_not_installed(lang):
            result = get_parser(lang)
            assert result is None, f"Expected None for {lang} (not installed)"


# ---------------------------------------------------------------------------
# Test: supported_languages returns expected list
# ---------------------------------------------------------------------------

def test_supported_languages_returns_sorted_list():
    """supported_languages returns a sorted list of language keys."""
    langs = supported_languages()
    assert langs == sorted(_LANG_LOADERS.keys())
    assert isinstance(langs, list)
    assert all(isinstance(l, str) for l in langs)


def test_supported_languages_contains_expected():
    """supported_languages contains the five expected languages."""
    langs = supported_languages()
    expected = {"java", "python", "javascript", "typescript", "go"}
    assert set(langs) == expected


# ---------------------------------------------------------------------------
# Test: cache behavior
# ---------------------------------------------------------------------------

def test_get_parser_cache_returns_same_object():
    """get_parser returns the same (Parser, Language) tuple on repeated calls."""
    result1 = get_parser("python")
    result2 = get_parser("python")
    assert result1 is result2


def test_get_parser_cache_clear():
    """lru_cache can be cleared and re-populated."""
    get_parser("python")  # populate cache
    get_parser.cache_clear()
    result = get_parser("python")
    assert result is not None
    parser, _ = result
    assert isinstance(parser, Parser)


def test_get_parser_cache_independent_languages():
    """Cache entries for different languages are independent."""
    python_result = get_parser("python")
    java_result = get_parser("java")
    assert python_result is not java_result
    # After clearing, both should still work
    get_parser.cache_clear()
    assert get_parser("python") is not None
    assert get_parser("java") is not None
