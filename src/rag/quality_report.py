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

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Dict, List, Any

from src.rag import grounding


# In-memory report structure
_report_lock = threading.Lock()
_report: Dict[str, Any] = {
    "g_version": grounding.G_VERSION,
    "indexed_at": grounding.iso_timestamp(),
    "codex": {
        "total_files": 0,
        "validation_passed": 0,
        "validation_failed_then_retried": 0,
        "abstained": 0,
        "files": [],
    },
    "synthesis": {},
    "ingest": {
        "total_chunks": 0,
        "skipped_incremental": 0,
        "added": 0,
    },
}


def _ensure_context_dir() -> Path:
    """Ensure context directory exists."""
    context_path = Path("context")
    context_path.mkdir(exist_ok=True, parents=True)
    return context_path


def _load_existing_report() -> Dict[str, Any]:
    """Load existing report if it exists."""
    report_path = _ensure_context_dir() / "quality_report.json"
    if report_path.exists():
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {
                "g_version": None,
                "indexed_at": None,
                "codex": {
                    "total_files": 0,
                    "validation_passed": 0,
                    "validation_failed_then_retried": 0,
                    "abstained": 0,
                    "files": [],
                },
                "synthesis": {},
                "ingest": {
                    "total_chunks": 0,
                    "skipped_incremental": 0,
                    "added": 0,
                },
            }
    return {
        "g_version": None,
        "indexed_at": None,
        "codex": {
            "total_files": 0,
            "validation_passed": 0,
            "validation_failed_then_retried": 0,
            "abstained": 0,
            "files": [],
        },
        "synthesis": {},
        "ingest": {
            "total_chunks": 0,
            "skipped_incremental": 0,
            "added": 0,
        },
    }


def _merge_reports(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    """Merge report data, preserving existing data where not overridden."""
    
    # Merge codex.files
    existing_files = {f["path"]: f for f in base.get("codex", {}).get("files", [])}
    new_files = {f["path"]: f for f in updates.get("codex", {}).get("files", [])}
    merged_files = list({**existing_files, **new_files}.values())
    
    merged = base.copy()
    merged.update(updates)
    merged["codex"]["files"] = merged_files
    
    # Preserve synthesis sections that aren't being updated
    if "synthesis" in base and "synthesis" in updates:
        for level, data in base["synthesis"].items():
            if level not in updates["synthesis"]:
                updates["synthesis"][level] = data
    
    return merged


def record_file_quality(path: str, meta: Dict[str, Any]) -> None:
    """Record quality metrics for a single file processed by codex.
    
    meta should contain:
    - attempts: int
    - abstained: bool
    - hallucinated_names_last_attempt: list[str]
    - validation_passed: bool
    - g_version: str
    """
    with _report_lock:
        _report["codex"]["total_files"] += 1
        
        file_entry = {
            "path": path,
            "attempts": meta.get("attempts", 1),
            "abstained": meta.get("abstained", False),
            "hallucinated_names": meta.get("hallucinated_names_last_attempt", []),
        }
        
        _report["codex"]["files"].append(file_entry)
        
        if meta.get("abstained"):
            _report["codex"]["abstained"] += 1
        elif meta.get("validation_passed"):
            _report["codex"]["validation_passed"] += 1
        else:
            _report["codex"]["validation_failed_then_retried"] += 1


def record_synthesis_quality(
    level: str, section_id: str, **kwargs: Any
) -> None:
    """Record quality metrics for synthesis at a specific level.
    
    kwargs can contain:
    - abstained: bool
    - removed_count: int
    """
    with _report_lock:
        level_data = _report["synthesis"].setdefault(level, {
            "sections": 0,
            "abstained": 0,
            "removed_count": 0,
        })
        level_data["sections"] += 1
        
        if kwargs.get("abstained"):
            level_data["abstained"] += 1
        if "removed_count" in kwargs:
            level_data["removed_count"] += kwargs["removed_count"]


def record_ingest_quality(
    total_chunks: int = 0,
    skipped_incremental: int = 0,
    added: int = 0,
) -> None:
    """Record quality metrics for ingestion."""
    with _report_lock:
        _report["ingest"]["total_chunks"] += total_chunks
        _report["ingest"]["skipped_incremental"] += skipped_incremental
        _report["ingest"]["added"] += added


def reset_report() -> None:
    """Reset the in-memory report to initial state."""
    global _report
    with _report_lock:
        _report = {
            "g_version": grounding.G_VERSION,
            "indexed_at": None,
            "codex": {
                "total_files": 0,
                "validation_passed": 0,
                "validation_failed_then_retried": 0,
                "abstained": 0,
                "files": [],
            },
            "synthesis": {},
            "ingest": {
                "total_chunks": 0,
                "skipped_incremental": 0,
                "added": 0,
            },
        }


def write_report() -> Path:
    """Flush in-memory report to context/quality_report.json. Return path."""
    global _report
    
    with _report_lock:
        # Load existing report to preserve data
        existing = _load_existing_report()
        merged = _merge_reports(existing, _report)
        merged["indexed_at"] = grounding.iso_timestamp()
        
        report_path = _ensure_context_dir() / "quality_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)
        
        # Reset in-memory report for next run
        _report = {
            "g_version": grounding.G_VERSION,
            "indexed_at": None,
            "codex": {
                "total_files": 0,
                "validation_passed": 0,
                "validation_failed_then_retried": 0,
                "abstained": 0,
                "files": [],
            },
            "synthesis": {},
            "ingest": {
                "total_chunks": 0,
                "skipped_incremental": 0,
                "added": 0,
            },
        }
        
        return report_path


def load_report() -> Dict[str, Any]:
    """Load the quality report from disk."""
    report_path = _ensure_context_dir() / "quality_report.json"
    if report_path.exists():
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {
                "g_version": None,
                "indexed_at": None,
                "codex": {
                    "total_files": 0,
                    "validation_passed": 0,
                    "validation_failed_then_retried": 0,
                    "abstained": 0,
                    "files": [],
                },
                "synthesis": {},
                "ingest": {
                    "total_chunks": 0,
                    "skipped_incremental": 0,
                    "added": 0,
                },
            }
    return {
        "g_version": None,
        "indexed_at": None,
        "codex": {
            "total_files": 0,
            "validation_passed": 0,
            "validation_failed_then_retried": 0,
            "abstained": 0,
            "files": [],
        },
        "synthesis": {},
        "ingest": {
            "total_chunks": 0,
            "skipped_incremental": 0,
            "added": 0,
        },
    }
