"""
web/docs_routes.py -- API routes for the Documentation Hub (/docs).
Serves the synthesis pyramid, RAG coverage stats, and time-travel changelog.
"""

import logging
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from fastapi.responses import FileResponse, JSONResponse

logger = logging.getLogger(__name__)

DOCS_DIR = Path("context/docs")
SYNTH_DIR = DOCS_DIR / "synthesis"
CHANGELOG_DIR = Path("context/changelog")

SKIP_DIRS = {
    "node_modules", "__pycache__", ".git", ".svn", ".hg",
    "dist", "build", ".next", "target", ".venv", "venv",
    ".idea", ".vscode", ".vectordb", "vendor",
}


def register_docs_routes(app, cfg, store):

    workspace = Path(cfg.get("_defaults", {}).get("workspace_path", "./workspace"))

    @app.get("/docs")
    async def docs_page():
        return FileResponse("web/docs.html")

    @app.get("/api/docs/tree")
    async def docs_tree():
        if not SYNTH_DIR.exists():
            return {"tree": [], "stats": {"total": 0}}
        tree = []
        files_by_level = defaultdict(list)
        for f in sorted(SYNTH_DIR.glob("*.md")):
            m = re.match(r"^(L\d+)_(.+)\.md$", f.name)
            if not m:
                continue
            level, rest = m.group(1), m.group(2)
            files_by_level[level].append({
                "name": f.name, "level": level,
                "label": rest.replace("_", " / "),
                "size": f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
            })
        labels = {"L0": "Architecture overview", "L1": "Layer overviews", "L2": "Module documentation"}
        for level in sorted(files_by_level.keys()):
            tree.append({"level": level, "label": labels.get(level, f"Level {level}"),
                         "count": len(files_by_level[level]), "files": files_by_level[level]})
        codex_docs = sorted(DOCS_DIR.glob("codex_*.md"))
        if codex_docs:
            tree.append({"level": "L3", "label": "Per-file documentation (codex)",
                         "count": len(codex_docs),
                         "files": [{"name": f.name, "level": "L3",
                                    "label": f.stem.replace("codex_", "").replace("_", "/"),
                                    "size": f.stat().st_size,
                                    "modified": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")}
                                   for f in codex_docs[:300]]})
        return {"tree": tree, "stats": {"total_docs": sum(i["count"] for i in tree)}}

    @app.get("/api/docs/file")
    async def docs_read_file(name: str):
        safe_name = Path(name).name
        for directory in [SYNTH_DIR, DOCS_DIR]:
            filepath = directory / safe_name
            if filepath.exists():
                try:
                    content = filepath.read_text(encoding="utf-8", errors="replace")
                    return {"name": safe_name, "content": content, "size": len(content),
                            "modified": datetime.fromtimestamp(filepath.stat().st_mtime).strftime("%Y-%m-%d %H:%M")}
                except Exception as e:
                    return JSONResponse({"error": str(e)}, status_code=500)
        return JSONResponse({"error": f"Not found: {safe_name}"}, status_code=404)

    @app.get("/api/docs/coverage")
    async def docs_rag_coverage():
        codex_stems = set()
        for f in DOCS_DIR.glob("codex_*.md"):
            codex_stems.add(f.stem)
        ws = workspace.resolve()
        covered, uncovered = [], []
        if ws.exists():
            for path in sorted(ws.rglob("*")):
                if not path.is_file():
                    continue
                try:
                    rel_parts = path.relative_to(ws).parts
                except ValueError:
                    continue
                if any(p in SKIP_DIRS or p.startswith(".") for p in rel_parts[:-1]):
                    continue
                rel_str = str(path.relative_to(ws))
                codex_name = "codex_" + rel_str.replace("/", "_").replace("\\", "_").replace(".", "_")
                has_doc = codex_name in codex_stems
                entry = {"file": rel_str, "documented": has_doc}
                if has_doc:
                    covered.append(entry)
                else:
                    uncovered.append(entry)
        total = len(covered) + len(uncovered)
        return {"total_files": total, "covered_files": len(covered),
                "coverage_pct": round(len(covered) / max(total, 1) * 100, 1),
                "index_chunks": store.count, "codex_docs": len(codex_stems),
                "covered": covered[:500], "uncovered": uncovered[:500]}

    @app.get("/api/docs/changelog")
    async def docs_changelog(limit: int = 30):
        if not CHANGELOG_DIR.exists():
            return {"entries": []}
        entries = []
        for f in sorted(CHANGELOG_DIR.glob("*.md"), reverse=True)[:limit]:
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
                first_line = content.strip().split("\n")[0].lstrip("# ").strip()
                entry_count = len(re.findall(r"^## ", content, re.MULTILINE))
                entries.append({"date": f.stem, "title": first_line,
                                "entries": entry_count, "size": f.stat().st_size})
            except Exception:
                pass
        return {"entries": entries}

    @app.get("/api/docs/changelog/{date}")
    async def docs_changelog_entry(date: str):
        safe = re.sub(r"[^0-9-]", "", date)
        filepath = CHANGELOG_DIR / f"{safe}.md"
        if not filepath.exists():
            return JSONResponse({"error": "Not found"}, status_code=404)
        return {"date": safe, "content": filepath.read_text(encoding="utf-8", errors="replace")}

    @app.get("/api/docs/stats")
    async def docs_stats():
        synth_count = len(list(SYNTH_DIR.glob("*.md"))) if SYNTH_DIR.exists() else 0
        codex_count = len(list(DOCS_DIR.glob("codex_*.md")))
        changelog_count = len(list(CHANGELOG_DIR.glob("*.md"))) if CHANGELOG_DIR.exists() else 0
        last_update = None
        if SYNTH_DIR.exists():
            files = list(SYNTH_DIR.glob("*.md"))
            if files:
                latest = max(files, key=lambda f: f.stat().st_mtime)
                last_update = datetime.fromtimestamp(latest.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        return {"synthesis_docs": synth_count, "codex_docs": codex_count,
                "changelog_entries": changelog_count, "index_chunks": store.count,
                "last_update": last_update}
