"""Codex output validator (fixed).

Replaces the previous validator that was rejecting English prose words,
real Java annotations, and XML/properties content as "hallucinations".

DESIGN PRINCIPLES
1. A candidate name must LOOK like a programmer identifier. Bare lowercase
   English words are NEVER candidates.
2. Comparison is case-insensitive on a curated set of "knowns".
3. Hard-coded English stopword list strips prose verbs / adjectives.
4. Annotations (@Foo), parenthesized fragments (@Foo("bar")), and
   string literals are normalized before lookup.
5. Validation is BYPASSED for non-source file types (XML, YAML, CSV,
   properties, JSON, MD) until per-format extractors exist.
6. The validator scans only the LLM RESPONSE, not the request payload.

USAGE

    from src.rag.validator import validate_doc

    issues = validate_doc(
        doc_text=llm_response,
        source_text=original_source_code,
        known_identifiers=extract_identifiers(source_text, language),
        noise_filter=load_noise_filter(config),
        language=language,            # "java" | "python" | "xml" | ...
        file_path=path_for_logging,
    )
    if not issues:
        # accept the doc
        ...
    else:
        # log + retry / abstain
        ...

issues is a list of dicts: [{"name": str, "kind": str, "snippet": str}]
where kind ∈ {"camelcase", "snake_case", "dotted", "backticked", "all_caps"}.
"""

from __future__ import annotations

import re
from typing import Iterable

# ---------------------------------------------------------------------------
# Hard-coded English stopwords. Kept short on purpose — extend with care.
# These are NEVER candidates regardless of context.
# ---------------------------------------------------------------------------
_ENGLISH_STOPWORDS: frozenset[str] = frozenset({
    # articles, conjunctions, prepositions
    "the", "a", "an", "and", "or", "but", "if", "then", "else", "as",
    "at", "by", "for", "from", "in", "into", "of", "on", "to", "with",
    "without", "within", "across", "after", "before", "between", "during",
    "through", "until", "while", "since", "above", "below", "over", "under",
    # demonstratives, pronouns
    "this", "that", "these", "those", "it", "its", "they", "them", "their",
    "we", "our", "us", "you", "your", "he", "she", "his", "her", "him",
    # auxiliaries / modals
    "is", "are", "was", "were", "be", "been", "being", "have", "has",
    "had", "having", "do", "does", "did", "doing", "will", "would",
    "shall", "should", "may", "might", "must", "can", "could",
    # common adverbs / quantifiers
    "all", "any", "some", "each", "every", "no", "not", "only", "very",
    "more", "most", "less", "least", "much", "many", "few", "several",
    "such", "same", "other", "another", "various", "different", "specific",
    "general", "particular", "certain", "particular", "common", "main",
    "primary", "secondary", "internal", "external", "default", "custom",
    # common verbs in code prose
    "provide", "provides", "provided", "providing",
    "contain", "contains", "contained", "containing",
    "define", "defines", "defined", "defining",
    "describe", "describes", "described", "describing",
    "represent", "represents", "represented", "representing",
    "implement", "implements", "implemented", "implementing",
    "include", "includes", "included", "including",
    "use", "uses", "used", "using",
    "handle", "handles", "handled", "handling",
    "manage", "manages", "managed", "managing",
    "support", "supports", "supported", "supporting",
    "return", "returns", "returned", "returning",
    "call", "calls", "called", "calling",
    "create", "creates", "created", "creating",
    "build", "builds", "built", "building",
    "load", "loads", "loaded", "loading",
    "store", "stores", "stored", "storing",
    "read", "reads", "reading", "retrieves", "retrieve", "retrieved", "retrieving",
    "write", "writes", "written", "writing",
    "set", "sets", "setting", "settings",
    "get", "gets", "getting",
    "make", "makes", "made", "making",
    "check", "checks", "checked", "checking",
    "ensure", "ensures", "ensured", "ensuring",
    "allow", "allows", "allowed", "allowing",
    "expose", "exposes", "exposed", "exposing",
    "serve", "serves", "served", "serving",
    "annotate", "annotates", "annotated", "annotating",
    "map", "maps", "mapped", "mapping",
    "depend", "depends", "depended", "depending",
    "configure", "configures", "configured", "configuring",
    "indicate", "indicates", "indicated", "indicating",
    "specify", "specifies", "specified", "specifying",
    "explicit", "explicitly", "implicit", "implicitly",
    "name", "names", "named", "naming",
    # nouns common in code prose
    "code", "data", "value", "values", "type", "types", "field", "fields",
    "method", "methods", "function", "functions", "class", "classes",
    "object", "objects", "instance", "instances", "interface", "interfaces",
    "module", "modules", "package", "packages", "file", "files",
    "directory", "directories", "folder", "folders", "path", "paths",
    "input", "output", "result", "results", "purpose", "behavior",
    "feature", "features", "option", "options", "config", "configuration",
    "system", "systems", "framework", "frameworks", "library", "libraries",
    "service", "services", "server", "client", "request", "requests",
    "response", "responses", "context", "state", "status",
    "user", "users", "name", "value", "version", "schema",
    "section", "sections", "entry", "entries", "item", "items",
    "key", "keys", "string", "strings", "number", "numbers",
    "line", "lines", "row", "rows", "column", "columns",
    # connectors
    "based", "likely", "specifically", "essentially", "typically",
    "according", "indicated", "shown", "listed", "described",
    "following", "further", "above", "below", "additional",
    # placeholders that came from the prompt template (fix #5)
    "doc_md", "doc", "md",
})


# ---------------------------------------------------------------------------
# Candidate detection. A candidate must look like a programmer identifier.
# ---------------------------------------------------------------------------

# CamelCase: at least two humps so we don't catch words like "Application"
# without the user opting it into noise filter. (Tunable.)
_RE_CAMEL = re.compile(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b")

# snake_case: must contain an explicit underscore.
_RE_SNAKE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")

# ALL_CAPS_CONST: at least one underscore OR length >= 4 caps.
_RE_CONST = re.compile(r"\b[A-Z][A-Z0-9]{2,}(?:_[A-Z0-9]+)*\b")

# Dotted path: at least one dot, each segment ≥ 2 chars, alphanumeric.
_RE_DOTTED = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]+(?:\.[A-Za-z_][A-Za-z0-9_]+){1,}\b")

# Backticked: anything between backticks. Honored fully.
_RE_BACKTICK = re.compile(r"`([^`]+)`")


def extract_candidates(text: str) -> list[tuple[str, str]]:
    """Extract identifier-shaped tokens from text. Returns list of (name, kind)."""
    out: list[tuple[str, str]] = []
    for m in _RE_CAMEL.finditer(text):
        out.append((m.group(0), "camelcase"))
    for m in _RE_SNAKE.finditer(text):
        out.append((m.group(0), "snake_case"))
    for m in _RE_CONST.finditer(text):
        out.append((m.group(0), "all_caps"))
    for m in _RE_DOTTED.finditer(text):
        out.append((m.group(0), "dotted"))
    for m in _RE_BACKTICK.finditer(text):
        # Backtick contents need normalization (strip @, parens, quotes).
        normalized = _normalize_backticked(m.group(1))
        if normalized:
            out.append((normalized, "backticked"))
    return out


def _normalize_backticked(token: str) -> str | None:
    """Strip @, (...), trailing punctuation. Return cleaned token or None if empty."""
    # @Path("/x") -> Path
    token = token.strip()
    token = token.lstrip("@")
    # cut off at first paren or bracket
    for sep in ("(", "[", "<", " "):
        idx = token.find(sep)
        if idx > 0:
            token = token[:idx]
    # strip surrounding quotes / punctuation
    token = token.strip(".,:;\"'`")
    return token if token else None


# ---------------------------------------------------------------------------
# The validator
# ---------------------------------------------------------------------------

# File extensions where structural extraction works well. Outside this set,
# we BYPASS validation entirely (Bug #6 quick fix).
_VALIDATABLE_LANGUAGES: frozenset[str] = frozenset({"java", "python"})


def validate_doc(
    *,
    doc_text: str,
    source_text: str,
    known_identifiers: Iterable[str],
    noise_filter: Iterable[str],
    language: str,
    file_path: str = "",
) -> list[dict]:
    """Return list of issues. Empty list = doc passes.

    Each issue: {"name": str, "kind": str, "snippet": str}
    """
    # Bug #6 quick fix: skip non-source files
    if language not in _VALIDATABLE_LANGUAGES:
        return []

    # Build the lookup set: knowns + noise + stopwords, all lowercased.
    # Bug #2 fix: case-insensitive comparison.
    allowed_lower: set[str] = set()
    allowed_lower.update(s.lower() for s in known_identifiers)
    allowed_lower.update(s.lower() for s in noise_filter)
    allowed_lower.update(_ENGLISH_STOPWORDS)

    # Source text lowercased for substring fallback (annotations, literals).
    source_lower = source_text.lower()

    issues: list[dict] = []
    seen: set[str] = set()  # dedup within this doc

    for name, kind in extract_candidates(doc_text):
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)

        # Bug #3 fix: stopwords never count as hallucinations.
        if key in _ENGLISH_STOPWORDS:
            continue

        # Direct lookup against knowns + noise.
        if key in allowed_lower:
            continue

        # Bug #4 fix: substring lookup against the source.
        # Real annotations like Path / RequestMapping always appear in source.
        if key in source_lower:
            continue

        # Real hallucination.
        snippet = _surrounding_text(doc_text, name, 60)
        issues.append({"name": name, "kind": kind, "snippet": snippet})

    return issues


def _surrounding_text(text: str, needle: str, radius: int) -> str:
    idx = text.find(needle)
    if idx < 0:
        return ""
    a = max(0, idx - radius)
    b = min(len(text), idx + len(needle) + radius)
    return text[a:b].replace("\n", " ")
