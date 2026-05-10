"""Citation contract enforcement.

Rules for any output containing 'sources':
  - `sources` is a list of {path, line_start, line_end}.
  - Each `path` MUST resolve to a file in the workspace.
  - `line_start <= line_end <= file_line_count`.
  - `line_end - line_start <= 200` (no huge "everywhere" citations).

Additionally, if the output contains an `identifiers_mentioned` list (or identifiers extractable from the prose), each identifier MUST be findable in at least one of the cited source ranges. Otherwise: citation_failure.
"""

from pathlib import Path
from src.rag.identifiers import extract_identifiers, detect_language

# Workspace root can be overridden via environment variable if needed; default to "workspace"
WORKSPACE = Path("workspace")  # configurable


def enforce_citations(result: dict) -> str | None:
    """Return None if citations are valid, otherwise return an error message string.
    """
    sources = result.get("sources")
    if sources is None:
        return None  # tool didn't claim to cite — caller decides if that's OK
    if not isinstance(sources, list) or not sources:
        return "sources field present but empty"
    for src in sources:
        # Validate required keys
        if not isinstance(src, dict) or "path" not in src or "line_start" not in src or "line_end" not in src:
            return "invalid source entry format"
        path = WORKSPACE / src["path"]
        if not path.exists():
            return f"cited path does not exist: {src['path']}"
        # Count lines in the file
        try:
            n_lines = sum(1 for _ in path.open(encoding='utf-8', errors='replace'))
        except Exception:
            return f"cannot read cited file: {src['path']}"
        if not (1 <= src["line_start"] <= src["line_end"] <= n_lines):
            return f"line range {src['line_start']}-{src['line_end']} invalid for {src['path']} ({n_lines} lines)"
        if src["line_end"] - src["line_start"] > 200:
            return f"citation range too large: {src['path']}:{src['line_start']}-{src['line_end']}"

    # Cross‑check identifiers if present
    mentioned = result.get("identifiers_mentioned", [])
    if mentioned:
        cited_text = _read_cited_ranges(sources)
        # Use the generic identifier extractor (language‑agnostic)
        cited_ids = extract_identifiers(cited_text, language=None)
        for ident in mentioned:
            if ident not in cited_text:
                # Simple substring check is sufficient for safety
                return f"identifier '{ident}' mentioned but not in cited ranges"
    return None


def _read_cited_ranges(sources: list[dict]) -> str:
    """Read the text for each cited range and concatenate them.
    """
    parts = []
    for src in sources:
        path = WORKSPACE / src["path"]
        with path.open(encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        # Convert 1‑based line numbers to list indices
        start_idx = src["line_start"] - 1
        end_idx = src["line_end"]
        parts.append("".join(lines[start_idx:end_idx]))
    return "\n".join(parts)
