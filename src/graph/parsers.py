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
from typing import TYPE_CHECKING, Callable, Optional, Tuple

if TYPE_CHECKING:
    from tree_sitter import Language, Parser

# Forward declarations for lazy import.
# The actual tree_sitter import happens inside get_parser() to enable
# graceful degradation: topology-only operations work even when
# tree-sitter is not installed.

_LANG_LOADERS: dict[str, Callable[[], "Language"]] = {
    "java": lambda: _import_and_load("java"),
    "python": lambda: _import_and_load("python"),
    "javascript": lambda: _import_and_load("javascript"),
    "typescript": lambda: _import_and_load("typescript"),
    "go": lambda: _import_and_load("go"),
}


def _import_and_load(language: str) -> "Language":
    """Import and return the Language object for the given language.
    
    This function is called lazily inside get_parser(), allowing the
    parsers module to be imported even when tree-sitter is not installed.
    """
    from tree_sitter import Language  # type: ignore
    
    loaders: dict[str, Callable[[], tuple]] = {
        "java": lambda: (
            __import__("tree_sitter_java"),
            lambda mod: mod.language(),
        ),
        "python": lambda: (
            __import__("tree_sitter_python"),
            lambda mod: mod.language(),
        ),
        "javascript": lambda: (
            __import__("tree_sitter_javascript"),
            lambda mod: mod.language(),
        ),
        "typescript": lambda: (
            __import__("tree_sitter_typescript"),
            lambda mod: mod.language_typescript(),
        ),
        "go": lambda: (
            __import__("tree_sitter_go"),
            lambda mod: mod.language(),
        ),
    }
    
    mod_fn = loaders.get(language)
    if mod_fn is None:
        raise ValueError(f"Unknown language: {language}")
    
    mod, fn = mod_fn()
    return Language(fn(mod))


def get_parser(language: str) -> Optional[Tuple["Parser", "Language"]]:
    """Return (Parser, Language) or None if unavailable.
    
    This function is lazy: it imports tree_sitter only when called.
    If tree_sitter or the specific language package is not installed,
    returns None instead of raising an exception.
    """
    loader = _LANG_LOADERS.get(language)
    if loader is None:
        return None
    try:
        lang = loader()
    except (ImportError, ModuleNotFoundError, ValueError):
        return None
    from tree_sitter import Parser  # type: ignore
    parser = Parser(lang)
    return parser, lang


def supported_languages() -> list[str]:
    """Return sorted list of all known language keys (regardless of install)."""
    return sorted(_LANG_LOADERS.keys())
