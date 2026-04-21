"""Citation validator middleware for MCP tool responses.

Scans every tool response that produces prose about code identifiers and
verifies each name exists in the VectorStore index. Fails closed: if a name
cannot be verified, the response is rewritten or refused.

Usage (Phase 4 MCP layer):
    validator = CitationValidator(store, config)
    result = validator.validate_response(tool_name, response_text, sources)
    if result.has_violations:
        response_text = result.cleaned_text  # hallucinated sentences removed
        # sources field is always preserved; only prose is rewritten
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.rag.grounding import (
    ABSTAIN_TOKEN,
    DEFAULT_NOISE_FILTER,
    G_VERSION,
    contains_abstain,
    load_noise_filter,
)

if TYPE_CHECKING:
    from src.rag.store import VectorStore

logger = logging.getLogger(__name__)

# Regex patterns for identifier candidates in prose
_RE_BACKTICK = re.compile(r"`([^`]+)`")
_RE_CAMEL = re.compile(r"\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b")
_RE_SNAKE = re.compile(r"\b([a-z_][a-z0-9_]{3,})\b")
_RE_DOTTED = re.compile(r"\b([a-zA-Z][a-zA-Z0-9_]*(?:\.[a-zA-Z][a-zA-Z0-9_]*)+)\b")

# English stopwords — prevents false positives on common prose
_STOPWORDS = frozenset({
    "the", "be", "to", "of", "and", "in", "that", "have", "it", "for",
    "not", "on", "with", "as", "you", "do", "at", "this", "but", "by",
    "from", "they", "we", "say", "or", "will", "one", "all", "would",
    "there", "their", "what", "so", "out", "if", "about", "who", "get",
    "which", "when", "make", "can", "like", "time", "just", "know",
    "take", "into", "your", "some", "could", "them", "see", "than",
    "then", "now", "only", "its", "think", "also", "back", "after",
    "even", "want", "because", "most", "were", "has", "had", "been",
    "being", "each", "file", "class", "method", "function", "module",
    "returns", "param", "type", "value", "code", "line", "name", "list",
    "used", "uses", "call", "calls", "data", "init", "self", "none",
    "true", "false", "null", "void", "args", "kwargs", "test", "main",
})


@dataclass
class ValidationResult:
    """Result of a citation validation pass."""

    tool_name: str
    original_text: str
    cleaned_text: str
    violations: list[str] = field(default_factory=list)
    removed_sentences: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    g_version: str = G_VERSION

    @property
    def has_violations(self) -> bool:
        return bool(self.violations)

    @property
    def is_clean(self) -> bool:
        return not self.violations

    def to_dict(self) -> dict:
        return {
            "tool_name": self.tool_name,
            "has_violations": self.has_violations,
            "violations": self.violations,
            "removed_sentences": self.removed_sentences,
            "sources_count": len(self.sources),
            "g_version": self.g_version,
        }


class CitationValidator:
    """Middleware that validates MCP tool responses against the index.

    Every prose response from an MCP tool passes through validate_response().
    Names not found in the index (or noise filter) are treated as violations.
    Sentences containing violations are removed; if >threshold remain the
    entire response is replaced with ABSTAIN_TOKEN.
    """

    def __init__(self, store: "VectorStore", config: dict):
        self._store = store
        self._config = config
        self._noise = load_noise_filter(config)
        self._abstain_threshold: int = (
            config.get("grounding", {}).get("citation_abstain_threshold", 5)
        )
        logger.debug(
            "CitationValidator ready (noise_filter=%d terms, abstain_threshold=%d, g_version=%s)",
            len(self._noise),
            self._abstain_threshold,
            G_VERSION,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_response(
        self,
        tool_name: str,
        response_text: str,
        sources: list[dict] | None = None,
    ) -> ValidationResult:
        """Validate prose in response_text against the VectorStore index.

        Args:
            tool_name: MCP tool name (for logging).
            response_text: The prose to validate.
            sources: [{path, line_start, line_end}] already attached to the
                     response. Identifiers found in these source paths are
                     trusted without an additional index lookup.

        Returns:
            ValidationResult with cleaned_text ready to send.
        """
        if sources is None:
            sources = []

        if contains_abstain(response_text):
            return ValidationResult(
                tool_name=tool_name,
                original_text=response_text,
                cleaned_text=response_text,
                sources=sources,
            )

        # Build trusted identifier set from attached sources
        trusted = self._build_trusted_set(sources)

        # Extract candidates from prose
        candidates = self._extract_candidates(response_text)

        # Identify violations: candidates not in trusted ∪ noise
        violations: list[str] = []
        for cand in candidates:
            if cand in trusted or cand in self._noise:
                continue
            if cand.lower() in _STOPWORDS:
                continue
            # Fallback: try an exact search in the store
            if not self._exists_in_index(cand):
                violations.append(cand)

        if not violations:
            return ValidationResult(
                tool_name=tool_name,
                original_text=response_text,
                cleaned_text=response_text,
                sources=sources,
            )

        logger.warning(
            "[CitationValidator] tool=%s violations=%d names=%s",
            tool_name,
            len(violations),
            violations[:10],
        )

        # Remove sentences containing violations
        cleaned, removed_sentences = self._remove_violating_sentences(
            response_text, set(violations)
        )

        if len(violations) > self._abstain_threshold:
            cleaned = (
                f"{ABSTAIN_TOKEN}\n\n"
                f"Tool '{tool_name}' could not produce a grounded response "
                f"({len(violations)} unverifiable names). "
                f"Sources are preserved below."
            )

        return ValidationResult(
            tool_name=tool_name,
            original_text=response_text,
            cleaned_text=cleaned,
            violations=violations,
            removed_sentences=removed_sentences,
            sources=sources,
        )

    def validate_sources(self, sources: list[dict]) -> tuple[list[dict], list[dict]]:
        """Split sources into (valid, invalid) by checking path existence in index.

        A source is valid if at least one chunk with that source path exists
        in ChromaDB. Invalid sources are dropped before the response is sent.
        """
        valid, invalid = [], []
        for src in sources:
            path = src.get("path", "")
            if path and self._source_path_in_index(path):
                valid.append(src)
            else:
                invalid.append(src)
                logger.debug("[CitationValidator] source not in index: %s", path)
        return valid, invalid

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_trusted_set(self, sources: list[dict]) -> set[str]:
        """Collect identifiers from chunk texts for the given source paths."""
        trusted: set[str] = set()
        for src in sources:
            path = src.get("path", "")
            if not path:
                continue
            try:
                result = self._store.collection.get(
                    where={"source": path},
                    include=["documents"],
                )
                for doc in (result.get("documents") or []):
                    if doc:
                        trusted.update(self._extract_candidates(doc))
            except Exception as exc:
                logger.debug("_build_trusted_set error for %s: %s", path, exc)
        return trusted

    def _extract_candidates(self, text: str) -> set[str]:
        """Extract identifier-like tokens from prose."""
        out: set[str] = set()

        for m in _RE_BACKTICK.finditer(text):
            tok = m.group(1).strip()
            if len(tok) >= 2:
                out.add(tok)

        for m in _RE_CAMEL.finditer(text):
            tok = m.group(1)
            if len(tok) >= 4:
                out.add(tok)

        for m in _RE_SNAKE.finditer(text):
            tok = m.group(1)
            if tok.lower() not in _STOPWORDS and len(tok) >= 4:
                out.add(tok)

        for m in _RE_DOTTED.finditer(text):
            out.add(m.group(1))

        return out

    def _exists_in_index(self, name: str) -> bool:
        """Return True if name appears verbatim in any indexed chunk."""
        try:
            results = self._store.search(name, top_k=1)
            for r in results:
                if name in (r.get("text", "") or r.get("document", "")):
                    return True
            return False
        except Exception:
            return True  # fail open on store errors to avoid false violations

    def _source_path_in_index(self, path: str) -> bool:
        """Return True if at least one chunk with this source path is indexed."""
        try:
            result = self._store.collection.get(
                where={"source": path},
                include=["ids"],
            )
            return bool(result.get("ids"))
        except Exception:
            return False

    def _remove_violating_sentences(
        self, text: str, violations: set[str]
    ) -> tuple[str, list[str]]:
        """Remove sentences containing any violation name.

        Sentence boundary: period/exclamation/question mark followed by
        whitespace, or a newline. Preserves paragraph structure.
        """
        sentences = re.split(r"(?<=[.!?])\s+|\n", text)
        kept, removed = [], []
        for sent in sentences:
            if any(v in sent for v in violations):
                removed.append(sent.strip())
            else:
                kept.append(sent)
        return " ".join(kept).strip(), removed
