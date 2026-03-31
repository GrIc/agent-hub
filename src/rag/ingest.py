"""
Ingest documents from context/ and workspace/ folders.
Filters out binary assets (images, fonts, compiled files, etc.).
Supports: code, text, pptx, docx, pdf.

Each chunk is tagged with a `doc_level` metadata for hierarchical RAG:
  - L0: Architecture overview (synthesize.py output)
  - L1: Layer overviews (synthesize.py output)
  - L2: Module docs (synthesize.py output)
  - L3: Codex scan docs (codex_*.md)
  - code: Raw source code from workspace
  - context: Manual docs (architecture/, code-samples/)
  - report: Agent reports
"""

import os
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# -- Binary / asset extensions to SKIP ---

SKIP_DIRS = {
    "node_modules", "__pycache__", ".git", ".svn", ".hg",
    "dist", "build", ".next", ".nuxt", "target",
    ".venv", "venv", "env", ".env",
    ".vectordb", ".idea", ".vscode",
    "vendor", "bower_components",
}

MAX_FILE_SIZE = 1_000_000  # 1MB


# -- Parsers ---

def _read_text(path: Path) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        if content.count("\ufffd") > len(content) * 0.1:
            logger.debug(f"Skipping likely binary file: {path}")
            return ""
        return content
    except Exception as e:
        logger.warning(f"Cannot read {path}: {e}")
        return ""


def _read_pptx(path: Path) -> str:
    try:
        from pptx import Presentation
        prs = Presentation(str(path))
        parts = []
        for i, slide in enumerate(prs.slides, 1):
            slide_texts = []
            for shape in slide.shapes:
                if shape.has_text_frame:
                    slide_texts.append(shape.text_frame.text)
            if slide_texts:
                parts.append(f"[Slide {i}]\n" + "\n".join(slide_texts))
        return "\n\n".join(parts)
    except Exception as e:
        logger.warning(f"Cannot parse PPTX {path}: {e}")
        return ""


def _read_docx(path: Path) -> str:
    try:
        from docx import Document
        doc = Document(str(path))
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as e:
        logger.warning(f"Cannot parse DOCX {path}: {e}")
        return ""


def _read_pdf(path: Path) -> str:
    try:
        import fitz
        doc = fitz.open(str(path))
        parts = []
        for page in doc:
            parts.append(page.get_text())
        doc.close()
        return "\n\n".join(parts)
    except Exception as e:
        logger.warning(f"Cannot parse PDF {path}: {e}")
        return ""


PARSERS = {
    ".pptx": _read_pptx,
    ".docx": _read_docx,
    ".pdf": _read_pdf,
}


# -- Doc level detection ---

def detect_doc_level(relative_path: str, directory_label: str = "") -> str:
    """
    Detect the documentation level of a file for hierarchical RAG.

    Args:
        relative_path: Path relative to the ingestion directory
        directory_label: Label passed by the caller ("context", "workspace", "reports")

    Returns:
        One of: "L0", "L1", "L2", "L3", "code", "context", "report"
    """
    rel_lower = relative_path.lower()
    name = Path(relative_path).name.lower()

    # Reports
    if directory_label == "reports":
        return "report"

    # Workspace = raw code
    if directory_label == "workspace":
        return "code"

    # Context directory: detect synthesis levels
    if directory_label == "context":
        # Synthesis outputs
        if "synthesis/" in rel_lower or "synthesis\\" in rel_lower:
            m = re.match(r"^(l\d+)_", name)
            if m:
                return m.group(1).upper()
        # Codex scan docs
        if name.startswith("codex_"):
            return "L3"

        # Manual context docs
        return "context"

    # Fallback
    return "context"


# -- Chunking ---

def chunk_text(
    text: str,
    chunk_size: int = 1500,
    overlap: int = 200,
    source: str = "",
    doc_level: str = "context",
) -> list[dict]:
    """
    Split text into chunks with metadata.

    Each chunk dict contains: text, source, chunk_index, doc_level.
    """
    if not text.strip():
        return []

    chunks = []
    start = 0
    idx = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]

        if end < len(text):
            last_nl = chunk.rfind("\n")
            if last_nl > chunk_size // 2:
                end = start + last_nl + 1
                chunk = text[start:end]

        chunks.append({
            "text": chunk.strip(),
            "source": source,
            "chunk_index": idx,
            "doc_level": doc_level,
        })
        start = end - overlap
        idx += 1

    return chunks


# -- Ingestion pipeline ---

def _should_skip_dir(dirname: str, skip_dirs: set[str] = SKIP_DIRS) -> bool:
    return dirname in skip_dirs or dirname.startswith(".")


def _should_skip_file(path: Path, allowed_extensions: set[str], max_file_size: int = MAX_FILE_SIZE) -> bool:
    """Skip files that don't match our criteria.

    - Must be in allowed_extensions (if specified)
    - Must not exceed max_file_size
    - Minified files are always skipped
    """
    suffix = path.suffix.lower()

    # Skip minified files (always)
    if path.name.endswith((".min.js", ".min.css", ".bundle.js", ".chunk.js")):
        return True

    # Skip by size
    try:
        if path.stat().st_size > max_file_size:
            return True
    except OSError:
        return True

    # Positive list: only index if extension is in allowed_extensions
    if allowed_extensions and suffix not in allowed_extensions:
        return True

    return False


def ingest_directory(
    directory: str | Path,
    extensions: Optional[list[str]] = None,
    chunk_size: int = 1500,
    chunk_overlap: int = 200,
    label: str = "",
    skip_dirs: Optional[set[str]] = None,
    max_file_size: Optional[int] = None,
) -> list[dict]:
    """
    Recursively read all matching files, parse, and chunk.

    Args:
        directory: Directory to scan
        extensions: Allowed file extensions (None = all)
        chunk_size: Chunk size in chars
        chunk_overlap: Overlap between chunks
        label: Directory label for doc_level detection ("context", "workspace", "reports")

    Returns:
        List of {text, source, chunk_index, doc_level} dicts.
    """
    directory = Path(directory)
    if not directory.exists():
        logger.warning(f"Directory {directory} does not exist")
        return []

    _skip_dirs = skip_dirs if skip_dirs is not None else SKIP_DIRS
    _max_file_size = max_file_size if max_file_size is not None else MAX_FILE_SIZE
    allowed = set(extensions) if extensions else set()
    all_chunks = []
    skipped = 0

    all_paths = []
    for dirpath, dirnames, filenames in os.walk(directory, followlinks=True):
        dirnames[:] = [d for d in dirnames if d not in _skip_dirs and not d.startswith(".")]
        for fname in filenames:
            all_paths.append(Path(dirpath) / fname)
    for path in sorted(all_paths):
        if not path.is_file():
            continue
        if any(_should_skip_dir(part, _skip_dirs) for part in path.relative_to(directory).parts[:-1]):
            continue
        if _should_skip_file(path, allowed, _max_file_size):
            skipped += 1
            continue

        logger.info(f"Ingesting: {path}")

        parser = PARSERS.get(path.suffix.lower(), _read_text)
        text = parser(path)
        if not text.strip():
            continue

        relative = path.relative_to(directory) if directory in path.parents or directory == path.parent else path.name
        relative_str = str(relative)
        header = f"[File: {relative_str}]\n"
        text_with_header = header + text

        doc_level = detect_doc_level(relative_str, label)

        chunks = chunk_text(
            text_with_header,
            chunk_size=chunk_size,
            overlap=chunk_overlap,
            source=relative_str,
            doc_level=doc_level,
        )
        all_chunks.extend(chunks)

    # Log level distribution
    level_counts = {}
    for c in all_chunks:
        lvl = c.get("doc_level", "?")
        level_counts[lvl] = level_counts.get(lvl, 0) + 1

    logger.info(
        f"Ingested {len(all_chunks)} chunks from {directory} "
        f"(skipped {skipped} binary/asset files) "
        f"levels: {level_counts}"
    )
    return all_chunks
