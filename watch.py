#!/usr/bin/env python3
"""
watch.py -- Detect modified files in the workspace,
re-document changed files and update the RAG.

Usage:
    python watch.py                  # Full scan, process changes
    python watch.py --dry-run        # Show changes without acting
    python watch.py --reset          # Delete state and start fresh
    python watch.py --status         # Show current state
"""

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

console = Console()

# Time-Travel changelog
try:
    from src.changelog import generate_changelog_entry
    HAS_CHANGELOG = True
except ImportError:
    HAS_CHANGELOG = False

# -- Config ---

STATE_FILE = Path("output/.scan_state.json")
CONTEXT_DOCS_DIR = Path("context/docs")

CODE_EXTENSIONS = {
    ".py", ".java", ".js", ".ts", ".jsx", ".tsx", ".cs",
    ".sql", ".properties",
    ".xml", ".yaml", ".yml", ".json",
    ".html", ".css", ".scss",
    ".sh", ".bat", ".cmd",
    ".md", ".txt", ".rst",
}

SKIP_DIRS = {
    "node_modules", "__pycache__", ".git", ".svn", ".hg",
    "dist", "build", ".next", "target", ".venv", "venv",
    ".idea", ".vscode", "vendor", ".vectordb",
}

MAX_FILE_SIZE = 200_000  # 200KB


# -- State management ---

def load_state() -> dict:
    """Load the scan state: {filepath: {mtime, size, content_hash, doc_file}}."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logging.warning(f"Cannot load state file: {e}")
    return {}


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def file_content_hash(path: Path) -> str:
    """Fast hash of file content for change detection.

    Normalizes line endings (CRLF -> LF) before hashing so that
    the same file mounted from Windows (CRLF) and Linux (LF) produces
    identical hashes. This prevents Docker containers from re-processing
    all files when the workspace is bind-mounted from a Windows host.
    """
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                # Normalize CRLF -> LF for consistent cross-platform hashing
                h.update(chunk.replace(b"\r\n", b"\n"))
    except OSError:
        return ""
    return h.hexdigest()


# -- File scanning ---

def scan_workspace(workspace: Path) -> dict[str, dict]:
    """Scan workspace and return current state of all code files."""
    current = {}

    all_paths = []
    for dirpath, dirnames, filenames in os.walk(workspace, followlinks=True):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fname in filenames:
            all_paths.append(Path(dirpath) / fname)
    for path in sorted(all_paths):
        if not path.is_file():
            continue

        relative = str(path.relative_to(workspace))

        parts = Path(relative).parts
        if any(p in SKIP_DIRS or p.startswith(".") for p in parts[:-1]):
            continue

        if path.suffix.lower() not in CODE_EXTENSIONS:
            continue

        try:
            stat = path.stat()
            if stat.st_size > MAX_FILE_SIZE:
                continue
        except OSError:
            continue

        current[relative] = {
            "mtime": stat.st_mtime,
            "size": stat.st_size,
            "content_hash": file_content_hash(path),
        }

    return current


def diff_states(old_state: dict, new_state: dict) -> dict:
    """Compare old and new states. Returns {added, modified, deleted}."""
    old_files = set(old_state.keys())
    new_files = set(new_state.keys())

    added = sorted(new_files - old_files)
    deleted = sorted(old_files - new_files)

    modified = []
    for f in sorted(old_files & new_files):
        old_hash = old_state[f].get("content_hash", "")
        new_hash = new_state[f].get("content_hash", "")
        if old_hash != new_hash:
            modified.append(f)

    return {"added": added, "modified": modified, "deleted": deleted}


# -- Doc generation ---

def generate_doc_for_file(filepath: str, workspace: Path, client, model: str) -> str | None:
    """Generate documentation for a single file using the LLM."""
    full_path = workspace / filepath

    try:
        content = full_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        logging.error(f"Cannot read {filepath}: {e}")
        return None

    if not content.strip():
        return None

    if len(content) > 24000:
        content = content[:24000] + "\n\n[... file truncated]"

    prompt_system = (
        "You are a code analyst. Document the file below concisely.\n"
        "Produce:\n"
        "- Overview (2-3 sentences)\n"
        "- Main components (classes, functions, with their role)\n"
        "- Dependencies\n"
        "- Notable specifics\n"
        "Be factual and concise. Write in English."
    )

    prompt_user = f"File: {filepath}\n\n```\n{content}\n```"

    try:
        response = client.chat(
            messages=[
                {"role": "system", "content": prompt_system},
                {"role": "user", "content": prompt_user},
            ],
            model=model,
            temperature=0.2,
            max_tokens=2048,
        )
        return f"# Documentation -- {filepath}\n\n{response}"
    except Exception as e:
        logging.error(f"LLM doc generation failed for {filepath}: {e}")
        return None


def doc_filename_for(filepath: str) -> str:
    """Generate a deterministic doc filename for a source file."""
    safe = filepath.replace("/", "_").replace("\\", "_").replace(".", "_")
    return f"codex_{safe}.md"


def save_doc(filepath: str, content: str) -> Path:
    CONTEXT_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    doc_file = CONTEXT_DOCS_DIR / doc_filename_for(filepath)
    doc_file.write_text(content, encoding="utf-8")
    return doc_file


def delete_doc(filepath: str) -> bool:
    doc_file = CONTEXT_DOCS_DIR / doc_filename_for(filepath)
    if doc_file.exists():
        doc_file.unlink()
        return True
    return False


# -- RAG incremental update ---

def update_rag_for_files(changed_files: list[str], workspace: Path, cfg: dict):
    """Update the RAG index for only the changed files."""
    from src.client import ResilientClient
    from src.rag.store import VectorStore
    from src.rag.ingest import chunk_text

    defaults = cfg.get("_defaults", {})
    client = ResilientClient(
        api_key=defaults["api_key"],
        base_url=defaults["api_base_url"],
        max_retries=defaults.get("retry_max_attempts", 8),
        base_delay=defaults.get("retry_base_delay", 2.0),
        max_delay=defaults.get("retry_max_delay", 120.0),
    )

    embed_model = cfg["models"].get("embed", "")
    store = VectorStore(client=client, embed_model=embed_model)

    rag_cfg = cfg.get("rag", {})
    chunk_size = rag_cfg.get("chunk_size", 1000)
    chunk_overlap = rag_cfg.get("chunk_overlap", 150)

    # 1. Delete old chunks for changed files
    for filepath in changed_files:
        try:
            results = store.collection.get(where={"source": filepath}, include=[])
            if results["ids"]:
                store.collection.delete(ids=results["ids"])
                logging.info(f"[RAG] Deleted {len(results['ids'])} old chunks for {filepath}")
        except Exception as e:
            logging.warning(f"[RAG] Cannot delete old chunks for {filepath}: {e}")

    # 2. Also delete chunks for corresponding doc files
    for filepath in changed_files:
        doc_source = f"docs/{doc_filename_for(filepath)}"
        try:
            results = store.collection.get(where={"source": doc_source}, include=[])
            if results["ids"]:
                store.collection.delete(ids=results["ids"])
                logging.info(f"[RAG] Deleted {len(results['ids'])} old doc chunks for {doc_source}")
        except Exception:
            pass

    # 3. Re-index: source code + generated doc
    new_chunks = []

    for filepath in changed_files:
        full_path = workspace / filepath
        if full_path.exists():
            try:
                content = full_path.read_text(encoding="utf-8", errors="replace")
                if content.strip():
                    header = f"[File: {filepath}]\n"
                    chunks = chunk_text(header + content, chunk_size=chunk_size, overlap=chunk_overlap, source=filepath, doc_level="code")
                    new_chunks.extend(chunks)
            except OSError:
                pass

        doc_path = CONTEXT_DOCS_DIR / doc_filename_for(filepath)
        if doc_path.exists():
            try:
                doc_content = doc_path.read_text(encoding="utf-8")
                if doc_content.strip():
                    doc_source = f"docs/{doc_filename_for(filepath)}"
                    chunks = chunk_text(doc_content, chunk_size=chunk_size, overlap=chunk_overlap, source=doc_source, doc_level="L3")
                    new_chunks.extend(chunks)
            except OSError:
                pass

    if new_chunks:
        added = store.add_chunks(new_chunks)
        logging.info(f"[RAG] Added {added} new chunks for {len(changed_files)} files")
    else:
        logging.info("[RAG] No new chunks to add")


# -- Main ---

def main():
    parser = argparse.ArgumentParser(description="Watch -- Incremental change detection and RAG update")
    parser.add_argument("--dry-run", "-n", action="store_true", help="Show changes without acting")
    parser.add_argument("--reset", action="store_true", help="Delete state and start fresh")
    parser.add_argument("--status", action="store_true", help="Show current state")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logs")
    parser.add_argument("--config", "-c", default="config.yaml", help="Configuration file")
    parser.add_argument("--no-rag", action="store_true", help="Generate docs but do not update the RAG")
    parser.add_argument("--bootstrap", action="store_true",
                        help="Snapshot current workspace state without LLM or RAG update. "
                            "Use after a manual prechauffe (codex + synthesize + ingest) "
                            "to initialize watch state without re-processing all files.")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level, format="%(message)s",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)

    from src.config import load_config
    cfg = load_config(args.config)
    defaults = cfg.get("_defaults", {})
    workspace = Path(defaults.get("workspace_path", "./workspace")).resolve()

    if not workspace.exists():
        console.print(f"[red]Workspace not found: {workspace}[/red]")
        sys.exit(1)

    if args.reset:
        if STATE_FILE.exists():
            STATE_FILE.unlink()
            console.print("[yellow]State deleted. Next scan will process all files.[/yellow]")
        else:
            console.print("[dim]No state to delete.[/dim]")
        sys.exit(0)

    if args.bootstrap:
        console.print(f"[bold blue]Bootstrapping state from workspace: {workspace}[/bold blue]")
        current_state = scan_workspace(workspace)
        console.print(f"   {len(current_state)} files found")
        save_state(current_state)
        console.print(f"[green]State bootstrapped ({len(current_state)} files). "
                      f"Next watch cycle will only process real changes.[/green]")
        sys.exit(0)

    console.print(f"[bold blue]Scanning workspace: {workspace}[/bold blue]")
    current_state = scan_workspace(workspace)
    console.print(f"   {len(current_state)} code files found")

    old_state = load_state()

    if args.status:
        if not old_state:
            console.print("[yellow]No previous state. Run a first scan without --status.[/yellow]")
        else:
            console.print(f"   Previous state: {len(old_state)} files")
            diff = diff_states(old_state, current_state)
            console.print(f"   Added: {len(diff['added'])}")
            console.print(f"   Modified: {len(diff['modified'])}")
            console.print(f"   Deleted: {len(diff['deleted'])}")
        sys.exit(0)

    if not old_state:
        console.print("[yellow]First scan -- all files will be processed.[/yellow]")
        diff = {"added": sorted(current_state.keys()), "modified": [], "deleted": []}
    else:
        diff = diff_states(old_state, current_state)

    total_changes = len(diff["added"]) + len(diff["modified"]) + len(diff["deleted"])

    if total_changes == 0:
        console.print("[green]No changes detected.[/green]")
        save_state(current_state)
        sys.exit(0)

    table = Table(title=f"Changes detected: {total_changes}")
    table.add_column("Action", style="bold", width=10)
    table.add_column("File")

    for f in diff["added"][:30]:
        table.add_row("[green]+ added[/green]", f)
    for f in diff["modified"][:30]:
        table.add_row("[yellow]~ modified[/yellow]", f)
    for f in diff["deleted"][:30]:
        table.add_row("[red]- deleted[/red]", f)

    remaining = total_changes - min(total_changes, 90)
    if remaining > 0:
        table.add_row("...", f"and {remaining} more")

    console.print(table)

    if args.dry_run:
        console.print("[dim]Dry run -- no action taken.[/dim]")
        sys.exit(0)

    if not defaults.get("api_base_url") or not defaults.get("api_key"):
        console.print("[red]API_BASE_URL and API_KEY required in .env for re-documentation.[/red]")
        sys.exit(1)

    from src.client import ResilientClient
    client = ResilientClient(
        api_key=defaults["api_key"],
        base_url=defaults["api_base_url"],
        max_retries=defaults.get("retry_max_attempts", 8),
        base_delay=defaults.get("retry_base_delay", 2.0),
        max_delay=defaults.get("retry_max_delay", 120.0),
    )

    from src.config import get_model_for_agent
    model = get_model_for_agent(cfg, "codex")

    files_to_doc = diff["added"] + diff["modified"]
    files_to_delete = diff["deleted"]
    all_changed = files_to_doc + files_to_delete

    for filepath in files_to_delete:
        if delete_doc(filepath):
            console.print(f"  Doc deleted: {filepath}")

    doc_generated = 0
    doc_failed = 0

    if files_to_doc:
        console.print(f"\n[bold blue]Re-documenting {len(files_to_doc)} file(s)...[/bold blue]")

        for i, filepath in enumerate(files_to_doc, 1):
            console.print(f"  [{i}/{len(files_to_doc)}] {filepath}...", end=" ")

            doc_content = generate_doc_for_file(filepath, workspace, client, model)
            if doc_content:
                doc_path = save_doc(filepath, doc_content)
                console.print(f"[green]OK[/green]")
                doc_generated += 1

                if filepath in current_state:
                    current_state[filepath]["doc_file"] = str(doc_path)
            else:
                console.print(f"[yellow]skip[/yellow]")
                doc_failed += 1

            if i < len(files_to_doc):
                time.sleep(2)

    console.print(f"\nDocumentation: {doc_generated} generated, {doc_failed} failed, {len(files_to_delete)} deleted")

    if not args.no_rag and all_changed:
        console.print(f"\n[bold blue]Updating RAG for {len(all_changed)} file(s)...[/bold blue]")
        try:
            update_rag_for_files(all_changed, workspace, cfg)
            console.print("[green]RAG updated.[/green]")
        except Exception as e:
            console.print(f"[red]RAG error: {e}[/red]")
            logging.exception("RAG update failed")

    # Generate Time-Travel changelog entry
    if HAS_CHANGELOG and not args.dry_run and total_changes > 0:
        try:
            generate_changelog_entry(
                diff=diff,
                workspace=workspace,
                client=client,
                model=model,
            )
        except Exception as e:
            console.print(f"[yellow]Changelog generation failed: {e}[/yellow]")

    save_state(current_state)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    console.print(f"\n[green]State saved ({timestamp}). Next scan will only process new changes.[/green]")


if __name__ == "__main__":
    main()
