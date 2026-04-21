"""Quality metrics writer for the indexing pipeline.

Reads/writes context/quality_report.json. Thread-safe append.


Schema:
{
  "g_version": "1.0.0",
  "indexed_at": "2026-04-18T...",
  "codex": {
    "total_files": 1234,
    "validation_passed": 1100,
    "validation_failed_then_retried": 100,
    "abstained": 34,
    "files": [
      {"path": "...", "attempts": 2, "abstained": false, "hallucinated_names": [...]},
      ...
    ]
  },
  "synthesis": {
    "L0": {"sections": 1, "abstained": 0, "removed_count": 0},
    "L1": {"sections": 8, "abstained": 0, "removed_count": 3},
    ...
  },
  "ingest": {
    "total_chunks": 9876,
    "skipped_incremental": 9000,
    "added": 876
  }
}
"""

import json
import threading
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime


# Global state for thread-safe reporting
_report_lock = threading.Lock()
_codex_entries: List[Dict[str, Any]] = []
_synthesis_entries: Dict[str, Dict[str, Any]] = {}
_ingest_metrics: Dict[str, Any] = {}


def _ensure_report_dir() -> Path:
    """Ensure context directory exists."""
    context_dir = Path("context")
    context_dir.mkdir(exist_ok=True)
    return context_dir


def _load_existing_report() -> Dict[str, Any]:
    """Load existing report if it exists."""
    report_path = _ensure_report_dir() / "quality_report.json"
    if report_path.exists():
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {"codex": {"files": []}, "synthesis": {}, "ingest": {}}
    return {"codex": {"files": []}, "synthesis": {}, "ingest": {}}


def record_file_quality(path: str, meta: Dict[str, Any]) -> None:
    """Record quality metrics for a single file processed by codex.
    
    Args:
        path: File path relative to workspace
        meta: Dictionary with keys:
            - attempts: int
            - abstained: bool
            - hallucinated_names_last_attempt: list[str]
            - validation_passed: bool
            - g_version: str
    """
    global _codex_entries
    
    entry = {
        "path": path,
        "attempts": meta.get("attempts", 0),
        "abstained": meta.get("abstained", False),
        "hallucinated_names": meta.get("hallucinated_names_last_attempt", []),
        "validation_passed": meta.get("validation_passed", False),
        "g_version": meta.get("g_version", "unknown"),
    }
    
    with _report_lock:
        _codex_entries.append(entry)


def record_synthesis_quality(
    level: str,
    section_id: str,
    abstained: bool = False,
    removed_count: int = 0,
) -> None:
    """Record quality metrics for synthesis output.
    
    Args:
        level: Synthesis level (L0, L1, L2, L3-aggregate)
        section_id: Identifier for the section being synthesized
        abstained: Whether the section was abstained
        removed_count: Number of hallucinated names removed
    """
    global _synthesis_entries
    
    if level not in _synthesis_entries:
        _synthesis_entries[level] = {"sections": 0, "abstained": 0, "removed_count": 0}
    
    _synthesis_entries[level]["sections"] += 1
    if abstained:
        _synthesis_entries[level]["abstained"] += 1
    _synthesis_entries[level]["removed_count"] += removed_count


def record_ingest_metrics(total_chunks: int, skipped_incremental: int, added: int) -> None:
    """Record ingestion metrics.
    
    Args:
        total_chunks: Total chunks processed
        skipped_incremental: Chunks skipped due to incremental indexing
        added: Chunks added to vector store
    """
    global _ingest_metrics
    
    _ingest_metrics = {
        "total_chunks": total_chunks,
        "skipped_incremental": skipped_incremental,
        "added": added,
    }


def write_report() -> Path:
    """Flush in-memory report to context/quality_report.json. Return path."""
    report_path = _ensure_report_dir() / "quality_report.json"
    
    # Load existing report to preserve data across multiple runs
    existing = _load_existing_report()
    
    # Build new report
    report = {
        "g_version": "1.0.0",
        "indexed_at": datetime.utcnow().isoformat() + "Z",
        "codex": {
            "total_files": len(_codex_entries),
            "validation_passed": sum(1 for e in _codex_entries if e.get("validation_passed")),
            "validation_failed_then_retried": sum(1 for e in _codex_entries if e.get("attempts", 0) > 1),
            "abstained": sum(1 for e in _codex_entries if e.get("abstained")),
            "files": _codex_entries,
        },
        "synthesis": existing.get("synthesis", {})
        if existing.get("synthesis")
        else {
            level: {
                "sections": data.get("sections", 0),
                "abstained": data.get("abstained", 0),
                "removed_count": data.get("removed_count", 0),
            }
            for level, data in _synthesis_entries.items()
        },
        "ingest": _ingest_metrics,
    }
    
    # Merge existing synthesis data
    if "synthesis" in existing:
        for level, data in existing["synthesis"].items():
            if level in report["synthesis"]:
                report["synthesis"][level]["sections"] += data.get("sections", 0)
                report["synthesis"][level]["abstained"] += data.get("abstained", 0)
                report["synthesis"][level]["removed_count"] += data.get("removed_count", 0)
            else:
                report["synthesis"][level] = data
    
    # Write report
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    return report_path


def load_report() -> Dict[str, Any]:
    """Load the quality report from disk.
    
    Returns:
        Dictionary with report data, or empty dict if file doesn't exist
    """
    report_path = _ensure_report_dir() / "quality_report.json"
    if report_path.exists():
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}
