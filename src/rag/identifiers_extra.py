"""Identifier extraction from source code (updated for codex validator fix).

Adds:
- Java annotation names (@Path, @ApplicationPath, @Produces, ...) to the
  extracted set so the validator finds them.
- A `language_for_validation()` helper used by the codex pipeline to decide
  whether validation applies at all.

This is a partial spec — implementor should integrate with the existing
identifiers.py rather than replace it wholesale.
"""

from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Java annotation extraction
# ---------------------------------------------------------------------------

_RE_JAVA_ANNOTATION = re.compile(
    r"@([A-Z][A-Za-z0-9_]*)"   # captures Path from @Path, RequestMapping from @RequestMapping(...)
)

# Java string constants that look like identifiers used in annotations.
# e.g. @Path("/existFile") -> we want "existFile" in the known set.
_RE_JAVA_ANNOTATION_LITERAL = re.compile(
    r"@[A-Z]\w*\s*\(\s*\"([^\"]+)\""
)

# Properties / web.xml param-name = param-value pattern.
_RE_PROPS_KEY = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_.\-]*)\s*[=:]", re.MULTILINE)


def extract_java_annotations(source: str) -> set[str]:
    """Return the set of annotation names + their literal arguments.

    Examples extracted from a single Java file:
        @Path("/existFile")  ->  {"Path", "existFile"}
        @ApplicationPath("/Content")  ->  {"ApplicationPath", "Content"}
        @Produces(MediaType.APPLICATION_JSON)  ->  {"Produces"}  (literal not a string)
    """
    out: set[str] = set()
    out.update(m.group(1) for m in _RE_JAVA_ANNOTATION.finditer(source))
    for m in _RE_JAVA_ANNOTATION_LITERAL.finditer(source):
        literal = m.group(1).strip("/")
        # split on common separators to capture sub-paths
        for piece in re.split(r"[/.\-_]", literal):
            if piece and len(piece) >= 3:
                out.add(piece)
    return out


# ---------------------------------------------------------------------------
# Decision: validate this file or not?
# ---------------------------------------------------------------------------

# Languages where AST/regex extraction reliably populates known_identifiers
# enough that the validator's strict mode is safe.
_VALIDATABLE_EXTENSIONS: frozenset[str] = frozenset({".java", ".py"})


def should_validate_file(file_path: str) -> bool:
    """True if codex output for this file should be run through the validator.

    Conservative default: only Java and Python in the first iteration. XML,
    YAML, JSON, CSV, properties, MD, HTML are bypassed because their identifier
    extraction is too weak — false positives would dominate.

    Extend the allowlist when per-format extractors land.
    """
    return Path(file_path).suffix.lower() in _VALIDATABLE_EXTENSIONS


# ---------------------------------------------------------------------------
# Wiring suggestion (pseudocode for codex.py)
# ---------------------------------------------------------------------------
#
# In src/agents/codex.py, _generate_doc_for_file_strict():
#
#   from src.rag.identifiers_extra import (
#       extract_java_annotations, should_validate_file,
#   )
#   from src.rag.validator import validate_doc
#
#   if not should_validate_file(file_path):
#       # bypass: trust the grounded prompt for non-source files
#       doc = self._llm_call(system=prepend_grounding(...), user=source, ...)
#       return doc, {"attempts": 1, "abstained": False, "validation_passed": True,
#                    "g_version": G_VERSION, "skipped_validation": True}
#
#   known = extract_identifiers(source_code, language)
#   if language == "java":
#       known = known | extract_java_annotations(source_code)
#   noise = load_noise_filter(self.config)
#
#   for attempt in range(max_retries):
#       doc = self._llm_call(...)
#       if contains_abstain(doc):
#           return doc, {...}
#       issues = validate_doc(
#           doc_text=doc,
#           source_text=source_code,    # NEW: pass the source for substring fallback
#           known_identifiers=known,
#           noise_filter=noise,
#           language=language,
#           file_path=file_path,
#       )
#       if not issues:
#           return doc, {"attempts": attempt + 1, ...}
#       # Retry with stricter prompt naming the offending identifiers.
#       hallucinated = [i["name"] for i in issues]
#       ...
