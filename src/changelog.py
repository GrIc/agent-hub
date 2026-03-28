"""
Time-Travel Documentation — Architecture changelog generator.

Integrates with watch.py to produce a narrative changelog entry each time
code changes are detected. Each entry describes WHAT changed, WHY it matters
architecturally, and HOW modules are impacted.

Output: context/changelog/YYYY-MM-DD.md (one file per day, appended)

The changelog is:
  - Served via /api/changelog in the web UI
  - Integrated into the Documentation Hub page
  - Indexed into the RAG so agents can reference past changes
"""

import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

CHANGELOG_DIR = Path("context/changelog")


def generate_changelog_entry(
    diff: dict,
    workspace: Path,
    client,
    model: str,
    max_files_detail: int = 30,
) -> Path:
    """
    Generate a narrative changelog entry for today's detected changes.

    Args:
        diff: {"added": [...], "modified": [...], "deleted": [...]} from watch.py
        workspace: Path to the workspace root
        client: ResilientClient instance (for LLM calls)
        model: Model ID to use for narrative generation
        max_files_detail: Max number of files to include in the LLM prompt

    Returns:
        Path to the changelog file (created or appended).
    """
    CHANGELOG_DIR.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    now_time = datetime.now().strftime("%H:%M")
    filepath = CHANGELOG_DIR / f"{today}.md"

    added = diff.get("added", [])
    modified = diff.get("modified", [])
    deleted = diff.get("deleted", [])
    total = len(added) + len(modified) + len(deleted)

    if total == 0:
        return filepath

    # Build a summary of changes for the LLM
    change_summary = _build_change_summary(added, modified, deleted, workspace, max_files_detail)

    # Generate narrative via LLM
    narrative = _generate_narrative(change_summary, client, model, total)

    # Build the entry
    entry_lines = [
        f"## {now_time} — {total} file(s) changed",
        "",
    ]

    # Stats
    parts = []
    if added:
        parts.append(f"{len(added)} added")
    if modified:
        parts.append(f"{len(modified)} modified")
    if deleted:
        parts.append(f"{len(deleted)} deleted")
    entry_lines.append(f"**Changes**: {', '.join(parts)}")
    entry_lines.append("")

    # Narrative
    if narrative:
        entry_lines.append(narrative)
        entry_lines.append("")

    # File list (condensed)
    if added:
        entry_lines.append("**Added files:**")
        for f in added[:20]:
            entry_lines.append(f"- `{f}`")
        if len(added) > 20:
            entry_lines.append(f"- ... and {len(added) - 20} more")
        entry_lines.append("")

    if modified:
        entry_lines.append("**Modified files:**")
        for f in modified[:20]:
            entry_lines.append(f"- `{f}`")
        if len(modified) > 20:
            entry_lines.append(f"- ... and {len(modified) - 20} more")
        entry_lines.append("")

    if deleted:
        entry_lines.append("**Deleted files:**")
        for f in deleted[:20]:
            entry_lines.append(f"- `{f}`")
        if len(deleted) > 20:
            entry_lines.append(f"- ... and {len(deleted) - 20} more")
        entry_lines.append("")

    entry_lines.append("---")
    entry_lines.append("")

    entry_text = "\n".join(entry_lines)

    # Append to today's file (create with header if new)
    if not filepath.exists():
        header = f"# Changelog — {today}\n\n"
        filepath.write_text(header + entry_text, encoding="utf-8")
    else:
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(entry_text)

    logger.info(f"[Changelog] Entry added to {filepath} ({total} changes)")
    return filepath


def _build_change_summary(
    added: list[str],
    modified: list[str],
    deleted: list[str],
    workspace: Path,
    max_files: int,
) -> str:
    """Build a structured summary of changes for the LLM."""
    lines = []

    # Classify changes by directory/module
    modules = {}
    for f in (added + modified + deleted):
        parts = Path(f).parts
        module = parts[0] if parts else "root"
        if len(parts) > 1:
            module = "/".join(parts[:2])
        if module not in modules:
            modules[module] = {"added": [], "modified": [], "deleted": []}
        if f in added:
            modules[module]["added"].append(f)
        elif f in modified:
            modules[module]["modified"].append(f)
        else:
            modules[module]["deleted"].append(f)

    lines.append("Changes by module:")
    for module, changes in sorted(modules.items(), key=lambda x: -sum(len(v) for v in x[1].values())):
        total = sum(len(v) for v in changes.values())
        lines.append(f"\n  {module} ({total} files):")
        for action in ["added", "modified", "deleted"]:
            if changes[action]:
                files = changes[action][:5]
                extra = len(changes[action]) - 5
                fnames = ", ".join(Path(f).name for f in files)
                if extra > 0:
                    fnames += f" +{extra} more"
                lines.append(f"    {action}: {fnames}")

    # Read a sample of modified files to understand what changed
    sampled = 0
    lines.append("\nSample file contents (modified):")
    for f in modified[:max_files]:
        full_path = workspace / f
        if full_path.exists() and full_path.stat().st_size < 50000:
            try:
                content = full_path.read_text(encoding="utf-8", errors="replace")
                # Just the first 30 lines to give context
                preview = "\n".join(content.splitlines()[:30])
                lines.append(f"\n--- {f} (first 30 lines) ---")
                lines.append(preview)
                sampled += 1
                if sampled >= 5:
                    break
            except Exception:
                pass

    return "\n".join(lines)


def _generate_narrative(change_summary: str, client, model: str, total_changes: int) -> str:
    """Use the LLM to generate a narrative description of the changes."""
    if total_changes < 3:
        # Too few changes for a meaningful narrative
        return ""

    prompt = (
        "You are a technical changelog writer for a development team. "
        "Based on the file changes below, write a concise narrative (3-8 sentences) "
        "describing what the team worked on. Focus on:\n"
        "- What was the intent of these changes?\n"
        "- Which modules/layers are impacted?\n"
        "- Any architectural shifts or new patterns introduced?\n"
        "- If relevant, include a small Mermaid diagram showing impacted module relationships.\n\n"
        "Write in English. Be factual — describe what you see, don't speculate.\n"
        "If you include a Mermaid diagram, use ```mermaid fenced blocks.\n"
        "Keep the narrative brief and useful for a developer reading the changelog."
    )

    try:
        response = client.chat(
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": change_summary[:8000]},
            ],
            model=model,
            temperature=0.3,
            max_tokens=1024,
        )
        return response.strip()
    except Exception as e:
        logger.warning(f"[Changelog] Narrative generation failed: {e}")
        return ""


def list_changelog_entries(limit: int = 30) -> list[dict]:
    """List available changelog entries (most recent first)."""
    if not CHANGELOG_DIR.exists():
        return []

    entries = []
    for f in sorted(CHANGELOG_DIR.glob("*.md"), reverse=True)[:limit]:
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
            first_line = content.strip().split("\n")[0].lstrip("# ").strip()
            # Count entries in the file (## headers)
            import re
            entry_count = len(re.findall(r"^## ", content, re.MULTILINE))
            entries.append({
                "date": f.stem,
                "title": first_line,
                "filename": f.name,
                "entries": entry_count,
                "size": f.stat().st_size,
            })
        except Exception:
            pass

    return entries
