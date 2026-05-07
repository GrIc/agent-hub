"""Language loaders for tree-sitter.

The only module in src/graph/ allowed to import language-specific packages.
Every downstream consumer gets back a uniform (Parser, Language) pair.

To add a new language:
  1. pip install tree-sitter-<lang>
  2. Add one entry to _LANG_LOADERS below.
  3. Create queries/<lang>.scm.
  4. Add the mapping in config.yaml: graph.extensions.

No other file in src/graph/ changes.
"""

from functools import lru_cache
from typing import Callable, Optional, Tuple

from tree_sitter import Language, Parser


def _load_java() -> Language:
    import tree_sitter_java

    return Language(tree_sitter_java.language())


def _load_python() -> Language:
    import tree_sitter_python

    return Language(tree_sitter_python.language())


def _load_javascript() -> Language:
    import tree_sitter_javascript

    return Language(tree_sitter_javascript.language())


def _load_typescript() -> Language:
    import tree_sitter_typescript

    return Language(tree_sitter_typescript.language_typescript())


def _load_go() -> Language:
    import tree_sitter_go

    return Language(tree_sitter_go.language())


_LANG_LOADERS: dict[str, Callable[[], Language]] = {
    "java": _load_java,
    "python": _load_python,
    "javascript": _load_javascript,
    "typescript": _load_typescript,
    "go": _load_go,
}


@lru_cache(maxsize=None)
def get_parser(language: str) -> Optional[Tuple[Parser, Language]]:
    """Return (Parser, Language) or None if unavailable."""
    loader = _LANG_LOADERS.get(language)
    if loader is None:
        return None
    try:
        lang = loader()
    except ImportError:
        return None
    parser = Parser(lang)
    return parser, lang


def supported_languages() -> list[str]:
    """Return sorted list of all known language keys (regardless of install)."""
    return sorted(_LANG_LOADERS.keys())
