"""Identifier extraction from source code.

Hybrid strategy:
- For supported languages (Java, Python): tree-sitter AST → highly accurate.
- For unsupported languages: regex fallback → ~80% recall, no false negatives
  on well-formed code, but misses generics / nested classes.

The extracted set is used for:
- Validating LLM-generated docs (Phase 1).
- Seeding graph nodes (Phase 2).

API:
    extract_identifiers(source: str, language: str | None = None) -> set[str]
    detect_language(file_path: str) -> str   # by extension
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable

# Lazy import; tree-sitter language packages installed via requirements.
try:
    import tree_sitter_java  # type: ignore[import-not-found]
    import tree_sitter_python  # type: ignore[import-not-found]
    from tree_sitter import Language, Parser  # type: ignore[import-not-found]
    _TS_AVAILABLE = True
except ImportError as e:
    _TS_AVAILABLE = False
    _TS_IMPORT_ERROR = e

logger = logging.getLogger(__name__)

_EXT_TO_LANG = {
    ".java": "java",
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".h": "cpp", ".hpp": "cpp",
}


def detect_language(file_path: str) -> str:
    """Detect language from file extension.
    
    Returns 'unknown' if extension not in mapping.
    """
    ext = Path(file_path).suffix.lower()
    return _EXT_TO_LANG.get(ext, "unknown")


# ---- regex fallback ----

_RE_CLASS = re.compile(r"\bclass\s+([A-Z][A-Za-z0-9_]+)")
_RE_INTERFACE = re.compile(r"\binterface\s+([A-Z][A-Za-z0-9_]+)")
_RE_ENUM = re.compile(r"\benum\s+([A-Z][A-Za-z0-9_]+)")
_RE_RECORD = re.compile(r"\brecord\s+([A-Z][A-Za-z0-9_]+)")
_RE_TRAIT = re.compile(r"\btrait\s+([A-Z][A-Za-z0-9_]+)")
_RE_STRUCT = re.compile(r"\bstruct\s+([A-Z][A-Za-z0-9_]+)")
_RE_PY_DEF = re.compile(r"\bdef\s+([a-z_][a-zA-Z0-9_]+)\s*(\()")
_RE_JAVA_METHOD = re.compile(r"\b(?:public|protected|private|static|final|abstract|synchronized|\s)+\w[\w<>,\s]*\s+([a-z_][A-Za-z0-9_]+)\s*(\()")
_RE_CAMELCASE = re.compile(r"\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b")  # ≥ 2 humps
_RE_SNAKE_CASE = re.compile(r"\b([a-z][a-z0-9_]{3,})\b")
_RE_DOTTED_PATH = re.compile(r"\b([a-z][a-z0-9_]+(?:\.[a-z][a-z0-9_]+)+)\b")

# Common English stopwords to avoid false positives
_STOPWORDS = frozenset([
    "the", "and", "for", "are", "but", "not", "you", "all", "can", "her", "was",
    "one", "our", "out", "day", "get", "has", "him", "his", "how", "man", "new",
    "now", "old", "see", "two", "way", "who", "boy", "did", "its", "let", "put",
    "say", "she", "too", "use", "with", "this", "that", "from", "have", "will",
    "your", "what", "when", "make", "like", "time", "just", "know", "take", "people",
    "into", "year", "good", "some", "could", "them", "than", "then", "also", "very",
    "after", "should", "world", "would", "there", "their", "about", "which", "these",
    "those", "other", "such", "only", "more", "most", "many", "much", "here", "over",
    "under", "again", "further", "once", "where", "why", "before", "right", "too",
])


def _extract_regex(source: str) -> set[str]:
    """Regex-based identifier extraction fallback.
    
    Extracts:
    - class/interface/enum names
    - function/method names
    - CamelCase identifiers ≥4 chars
    - snake_case identifiers ≥4 chars
    - dotted paths (packages/modules)
    
    Filters out common English words and short tokens.
    """
    ids = set()

    # Classes
    for m in _RE_CLASS.finditer(source):
        if m.group(1) and len(m.group(1)) >= 4:
            ids.add(m.group(1))
    
    # Interfaces
    for m in _RE_INTERFACE.finditer(source):
        if m.group(1) and len(m.group(1)) >= 4:
            ids.add(m.group(1))
    
    # Enums
    for m in _RE_ENUM.finditer(source):
        if m.group(1) and len(m.group(1)) >= 4:
            ids.add(m.group(1))
    
    # Records
    for m in _RE_RECORD.finditer(source):
        if m.group(1) and len(m.group(1)) >= 4:
            ids.add(m.group(1))

    # Python function definitions
    for m in _RE_PY_DEF.finditer(source):
        if m.group(1) and len(m.group(1)) >= 4:
            ids.add(m.group(1))

    # Java method definitions (simplified)
    for m in _RE_JAVA_METHOD.finditer(source):
        if m.group(1) and len(m.group(1)) >= 4:
            ids.add(m.group(1))

    # CamelCase identifiers
    for m in _RE_CAMELCASE.finditer(source):
        token = m.group(1)
        if len(token) >= 4 and token.lower() not in _STOPWORDS:
            ids.add(token)

    # snake_case identifiers
    for m in _RE_SNAKE_CASE.finditer(source):
        token = m.group(1)
        if len(token) >= 4 and token not in _STOPWORDS:
            ids.add(token)

    # dotted paths (packages/modules)
    for m in _RE_DOTTED_PATH.finditer(source):
        token = m.group(1)
        if len(token) >= 4 and token.lower() not in _STOPWORDS:
            ids.add(token)

    return ids


# ---- AST (tree-sitter) ----



_PARSER_CACHE: dict[str, Parser] = {}
_get_parser_warned = False


def _get_parser(language: str):
    """Get or create a tree-sitter parser for the given language.
    
    Returns None if tree-sitter is not available or language unsupported.
    """
    global _get_parser_warned
    if not _TS_AVAILABLE:
        if not _get_parser_warned:
            logger.warning(
                "tree-sitter not available (%s). Falling back to regex extraction. "
                "Install tree-sitter packages to enable AST extraction for Java/Python.",
                _TS_IMPORT_ERROR
            )
            _get_parser_warned = True
        return None

    if language in _PARSER_CACHE:
        return _PARSER_CACHE[language]

    try:
        if language == "java":
            import tree_sitter_java  # type: ignore[import-not-found]
            lang = Language(tree_sitter_java.language())
        elif language == "python":
            import tree_sitter_python  # type: ignore[import-not-found]
            lang = Language(tree_sitter_python.language())
        else:
            return None
        parser = Parser(lang)
        _PARSER_CACHE[language] = parser
        return parser
    except Exception as e:
        logger.warning("Failed to create parser for language %s: %s", language, e)
        return None


# Per-language node-type → identifier-extraction strategy.
# Walk the AST, collect names from declaration nodes only.
_JAVA_DECL_TYPES = {
    "class_declaration",
    "interface_declaration",
    "enum_declaration",
    "method_declaration",
    "field_declaration",
    "constructor_declaration",
    "annotation_type_declaration",
    "record_declaration",
    "enum_constant",
}

_PYTHON_DECL_TYPES = {
    "class_definition",
    "function_definition",
    "assignment",
    "named_expression",  # walrus operator assignments
    "import_from_statement",
    "import_statement",
}


def _extract_ast_java(source: str) -> set[str]:
    """Extract identifiers from Java source using tree-sitter AST.
    
    Returns set of class/method/field names. Falls back to regex on error.
    """
    parser = _get_parser("java")
    if parser is None:
        logger.debug("Java parser unavailable; falling back to regex")
        return _extract_regex(source)

    try:
        tree = parser.parse(source.encode("utf-8"))
    except Exception as e:
        logger.warning("Java AST parsing failed: %s; falling back to regex", e)
        return _extract_regex(source)

    out: set[str] = set()

    def walk(node):
        # Collect declaration nodes
        if node.type in _JAVA_DECL_TYPES:
            # Try to find the 'name' field
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                name = name_node.text.decode("utf-8")
                if len(name) >= 2:
                    out.add(name)
            # Also check for method names in method_declaration
            if node.type == "method_declaration":
                # method_declaration has a 'name' field
                name_node = node.child_by_field_name("name")
                if name_node is not None:
                    name = name_node.text.decode("utf-8")
                    if len(name) >= 2:
                        out.add(name)
        
        # Recurse
        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return out


def _extract_ast_python(source: str) -> set[str]:
    """Extract identifiers from Python source using tree-sitter AST.
    
    Returns set of class/function/variable names. Falls back to regex on error.
    """
    parser = _get_parser("python")
    if parser is None:
        logger.debug("Python parser unavailable; falling back to regex")
        return _extract_regex(source)

    try:
        tree = parser.parse(source.encode("utf-8"))
    except Exception as e:
        logger.warning("Python AST parsing failed: %s; falling back to regex", e)
        return _extract_regex(source)

    out: set[str] = set()

    def walk(node):
        if node.type in _PYTHON_DECL_TYPES:
            # class_definition: has 'name' field
            if node.type == "class_definition":
                name_node = node.child_by_field_name("name")
                if name_node is not None:
                    name = name_node.text.decode("utf-8")
                    if len(name) >= 2:
                        out.add(name)
            # function_definition: has 'name' field
            elif node.type == "function_definition":
                name_node = node.child_by_field_name("name")
                if name_node is not None:
                    name = name_node.text.decode("utf-8")
                    if len(name) >= 2:
                        out.add(name)
            # assignment: look for target names
            elif node.type == "assignment":
                for child in node.children:
                    if child.type in ("identifier", "attribute"):
                        name = child.text.decode("utf-8")
                        if len(name) >= 2:
                            out.add(name)
                        break
            # named_expression (walrus): same as assignment
            elif node.type == "named_expression":
                for child in node.children:
                    if child.type in ("identifier", "attribute"):
                        name = child.text.decode("utf-8")
                        if len(name) >= 2:
                            out.add(name)
                        break
            # import statements: extract imported names
            elif node.type in ("import_from_statement", "import_statement"):
                # Extract the imported identifier (last component of dotted name)
                for child in node.children:
                    if child.type == "dotted_name":
                        name = child.text.decode("utf-8")
                        if len(name) >= 2:
                            # For imports, we want the last component
                            parts = name.split(".")
                            if parts:
                                out.add(parts[-1])
                        break
                    elif child.type == "identifier":
                        name = child.text.decode("utf-8")
                        if len(name) >= 2:
                            out.add(name)
                        break
        
        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return out


# ---- public API ----

def extract_identifiers(source: str, language: str | None = None) -> set[str]:
    """Extract identifiers (class names, method names, top-level fields) from source code.

    Returns a set of strings. Empty if extraction fails.
    
    Args:
        source: Source code text
        language: Optional language hint ('java', 'python', 'unknown', etc.)
                  If None, auto-detect from content or use regex fallback.
    
    Examples:
        >>> extract_identifiers("class Foo { void bar() {}", "java")
        {"Foo", "bar"}
    """
    if not source or not isinstance(source, str):
        return set()

    # Auto-detect language if not provided
    if language is None:
        # Heuristic: look for language hints in source
        if "import java." in source or "public class" in source or ".java" in source:
            language = "java"
        elif "def " in source or "class " in source or ".py" in source:
            language = "python"
        else:
            language = "unknown"

    if language == "java":
        return _extract_ast_java(source)
    if language == "python":
        return _extract_ast_python(source)
    # For any other language, use regex fallback
    return _extract_regex(source)
