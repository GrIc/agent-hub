#!/usr/bin/env python3
"""
synthesize.py -- Hierarchical documentation synthesis.

Reads all codex docs and produces a multi-level documentation pyramid:

  Level 0 -- ARCHITECTURE_OVERVIEW.md         (1 file, the big picture)
  Level 1 -- {BLOCK}_OVERVIEW.md              (1 per block: backend, frontend, database, tests...)
  Level 2 -- {BLOCK}_{MODULE}.md              (1 per module within a block)
  Level 3 -- codex_*.md                       (existing scan docs, untouched)

Build order: bottom-up (Level 2 -> Level 1 -> Level 0).

Usage:
    python synthesize.py --dry-run            # Show classification + plan
    python synthesize.py --classify           # Only classify docs into blocks
    python synthesize.py --level 2            # Build only Level 2
    python synthesize.py --level 1            # Build Level 2 + Level 1
    python synthesize.py                      # Build all levels (2 -> 1 -> 0)
    python synthesize.py --force              # Rebuild even if files exist
"""

import argparse
import logging
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

console = Console()
logger = logging.getLogger(__name__)

DOCS_DIR = Path("context/docs")
SYNTH_DIR = DOCS_DIR / "synthesis"

# -- Block definitions ---
# Each block has path patterns to match codex doc filenames or content.
# Order matters: first match wins. "other" is the catch-all.
# Customize via config.yaml synthesis.blocks.

DEFAULT_BLOCKS = {
    "tests": {
        "label": "Tests",
        "description": "Unit tests, integration tests, test utilities",
        "path_patterns": ["/test/", "/tests/", "Test.java", "Spec.js", ".test.", ".spec."],
    },
    "database": {
        "label": "Database",
        "description": "SQL scripts, schema definitions, data model, DDL",
        "path_patterns": [".sql", "/migrations/", "/ddl/", "/schema/"],
    },
    "frontend": {
        "label": "Frontend",
        "description": "JavaScript, TypeScript, HTML, CSS, web components, UI",
        "path_patterns": ["/js/", "/ts/", "/css/", "/html/", "/webapp/",
                          ".js_", ".ts_", ".jsx_", ".tsx_", ".vue_", ".html_", ".css_", ".scss_"],
    },
    "backend": {
        "label": "Backend",
        "description": "Server-side code, business logic, API",
        "path_patterns": [".java", "/com/", "/org/", "/java/", ".py_", "/api/"],
    },
    "other": {
        "label": "Other",
        "description": "Configuration, scripts, infrastructure, documentation, misc",
        "path_patterns": [],  # catch-all
    },
}


# -- Classification ---

def classify_doc(doc_path: Path, blocks: dict) -> str:
    """Classify a codex doc into a block based on filename and content."""
    name_lower = doc_path.stem.lower()

    try:
        content_head = doc_path.read_text(encoding="utf-8", errors="replace")[:500].lower()
    except Exception:
        content_head = ""

    searchable = name_lower + " " + content_head

    for block_name, block_def in blocks.items():
        if block_name == "other":
            continue
        for pattern in block_def.get("path_patterns", []):
            if pattern.lower() in searchable:
                return block_name

    return "other"


def extract_module_name(doc_path: Path, block_name: str) -> str:
    """Extract a module name from a codex doc filename."""
    stem = doc_path.stem

    clean = re.sub(r"^codex_", "", stem)
    clean = re.sub(r"_\d{8,}.*$", "", clean)

    parts = clean.split("_")

    skip = {"workspace", "src", "main", "java", "com", "org", "js", "ts", "html",
            "css", "test", "tests"}

    meaningful = [p for p in parts if p.lower() not in skip and len(p) > 1]

    if len(meaningful) >= 2:
        return "_".join(meaningful[-3:])
    elif meaningful:
        return meaningful[-1]
    else:
        return clean[-30:] if len(clean) > 30 else clean or "unknown"


def classify_all_docs(blocks: dict) -> dict:
    """Classify all codex docs into blocks and modules."""
    docs = sorted(DOCS_DIR.glob("codex_*.md"))
    if not docs:
        return {}

    result = defaultdict(lambda: defaultdict(list))
    for doc in docs:
        block = classify_doc(doc, blocks)
        module = extract_module_name(doc, block)
        result[block][module].append(doc)

    return dict(result)


# -- LLM Prompts ---

LEVEL2_PROMPT = """You are a senior software architect writing internal documentation.

Below are detailed docs for files in the **{module}** module ({block} layer).

Produce a MODULE DOCUMENTATION (500-1000 words) that covers:
1. **Purpose**: What this module does (2-3 sentences)
2. **Key components**: Main classes/files and their roles
3. **Internal flow**: How components interact within this module
4. **External dependencies**: What this module imports/calls from other modules
5. **Data model**: Key objects, types, or schemas managed by this module (if any)
6. **Entry points**: How other parts of the system call into this module

Write in English. Be factual -- only describe what the docs reveal.
Cite specific class/file names.

Source documentation:
"""

LEVEL1_PROMPT = """You are a senior software architect writing internal documentation.

Below are module-level summaries for the **{block}** layer of the application.

Produce a LAYER OVERVIEW (800-1500 words) that covers:
1. **Layer purpose**: What the {block} layer does overall (3-5 sentences)
2. **Module map**: Table of all modules, their role, and key classes
3. **Architecture patterns**: How modules are organized, design patterns used
4. **Inter-module dependencies**: How modules within this layer depend on each other
5. **External interfaces**: How this layer connects to other layers
6. **Data flow**: How data moves through this layer
7. **Key technologies**: Frameworks, libraries, tools specific to this layer

Write in English. Be factual.

Module summaries:
"""

LEVEL0_PROMPT = """You are a senior software architect producing the definitive architecture document for a development team.

Below are overviews of each architectural layer of the application.

Produce an ARCHITECTURE OVERVIEW (1500-2500 words) that covers:
1. **System overview**: What is this application? What business problem does it solve? (5-8 sentences)
2. **Technology stack**: Languages, frameworks, databases, infrastructure (table format)
3. **Architecture diagram** (describe in text): Layers, their responsibilities, and how they connect
4. **Layer summary**: Table with each layer, its purpose, module count, key technologies
5. **Cross-layer data flow**: How a typical request flows from user to database and back
6. **Integration points**: External systems, APIs, services
7. **Key architectural patterns**: Observed patterns across the whole system
8. **Data model overview**: Main business entities and their relationships (high-level)
9. **Entry points**: All the ways requests/data enter the system
10. **Known gaps**: What the documentation doesn't cover or where information is unclear

Write in English. This document is the single source of truth for understanding the system architecture.
Be precise. Reference specific module and class names where helpful.

Layer overviews:
"""


# -- Synthesis engine ---

class Synthesizer:
    def __init__(self, client, model: str, blocks: dict, force: bool = False):
        self.client = client
        self.model = model
        self.blocks = blocks
        self.force = force
        self.stats = {"llm_calls": 0, "skipped": 0, "failed": 0}

    def _llm_call(self, system: str, content: str, max_tokens: int = 4096) -> str:
        if len(content) > 30000:
            content = content[:30000] + "\n\n[... truncated -- remaining modules not shown]"

        self.stats["llm_calls"] += 1
        result = self.client.chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
            model=self.model,
            temperature=0.2,
            max_tokens=max_tokens,
        )
        time.sleep(2)
        return result

    def _save(self, filepath: Path, content: str, header_info: str = ""):
        filepath.parent.mkdir(parents=True, exist_ok=True)
        header = (
            f"> Auto-generated by synthesize.py on {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"> {header_info}\n"
            f"> Re-generate: `python synthesize.py`\n\n---\n\n"
        )
        filepath.write_text(header + content, encoding="utf-8")

    def build_level2(self, classification: dict) -> dict:
        console.print("\n[bold blue]=== Level 2: Module documentation ===[/bold blue]")
        level2_files = {}
        for block_name in sorted(classification.keys()):
            modules = classification[block_name]
            block_label = self.blocks.get(block_name, {}).get("label", block_name)
            level2_files[block_name] = {}
            for module_name in sorted(modules.keys()):
                doc_paths = modules[module_name]
                filename = f"L2_{block_name}_{module_name}.md"
                filepath = SYNTH_DIR / filename
                if filepath.exists() and not self.force:
                    console.print(f"  [dim]Skip {filename} (exists)[/dim]")
                    level2_files[block_name][module_name] = filepath
                    self.stats["skipped"] += 1
                    continue
                doc_contents = []
                for dp in doc_paths:
                    try:
                        text = dp.read_text(encoding="utf-8", errors="replace")
                        if len(text) > 8000:
                            text = text[:8000] + "\n[... truncated]"
                        doc_contents.append(f"### Source: {dp.name}\n{text}")
                    except Exception as e:
                        logger.warning(f"Cannot read {dp}: {e}")
                if not doc_contents:
                    continue
                combined = "\n\n".join(doc_contents)
                prompt = LEVEL2_PROMPT.format(module=module_name, block=block_label)
                console.print(f"  {filename} ({len(doc_paths)} source doc(s), {len(combined)} chars)...", end=" ")
                try:
                    result = self._llm_call(prompt, combined, max_tokens=2048)
                    title = f"# {block_label} -- {module_name}\n\n"
                    self._save(filepath, title + result,
                               f"Level 2 | {block_label} | Module: {module_name} | Sources: {len(doc_paths)}")
                    level2_files[block_name][module_name] = filepath
                    console.print("[green]OK[/green]")
                except Exception as e:
                    console.print(f"[red]FAIL: {e}[/red]")
                    self.stats["failed"] += 1
        return level2_files

    def build_level1(self, level2_files: dict) -> dict:
        console.print("\n[bold blue]=== Level 1: Layer overviews ===[/bold blue]")
        level1_files = {}
        for block_name in sorted(level2_files.keys()):
            modules = level2_files[block_name]
            if not modules:
                continue
            block_label = self.blocks.get(block_name, {}).get("label", block_name)
            block_desc = self.blocks.get(block_name, {}).get("description", "")
            filename = f"L1_{block_name}_OVERVIEW.md"
            filepath = SYNTH_DIR / filename
            if filepath.exists() and not self.force:
                console.print(f"  [dim]Skip {filename} (exists)[/dim]")
                level1_files[block_name] = filepath
                self.stats["skipped"] += 1
                continue
            module_contents = []
            for module_name, l2_path in sorted(modules.items()):
                try:
                    text = l2_path.read_text(encoding="utf-8", errors="replace")
                    text = re.sub(r"^>.*?\n---\n\n", "", text, flags=re.DOTALL)
                    module_contents.append(text)
                except Exception as e:
                    logger.warning(f"Cannot read {l2_path}: {e}")
            if not module_contents:
                continue
            combined = "\n\n---\n\n".join(module_contents)
            prompt = LEVEL1_PROMPT.format(block=block_label)
            console.print(f"  {filename} ({len(modules)} modules, {len(combined)} chars)...", end=" ")
            try:
                result = self._llm_call(prompt, combined, max_tokens=3072)
                title = f"# {block_label} -- Overview\n\n{block_desc}\n\n"
                self._save(filepath, title + result, f"Level 1 | {block_label} | Modules: {len(modules)}")
                level1_files[block_name] = filepath
                console.print("[green]OK[/green]")
            except Exception as e:
                console.print(f"[red]FAIL: {e}[/red]")
                self.stats["failed"] += 1
        return level1_files

    def build_level0(self, level1_files: dict) -> Path:
        console.print("\n[bold blue]=== Level 0: Architecture overview ===[/bold blue]")
        filepath = SYNTH_DIR / "L0_ARCHITECTURE_OVERVIEW.md"
        if filepath.exists() and not self.force:
            console.print(f"  [dim]Skip L0_ARCHITECTURE_OVERVIEW.md (exists)[/dim]")
            self.stats["skipped"] += 1
            return filepath
        layer_contents = []
        for block_name, l1_path in sorted(level1_files.items()):
            try:
                text = l1_path.read_text(encoding="utf-8", errors="replace")
                text = re.sub(r"^>.*?\n---\n\n", "", text, flags=re.DOTALL)
                layer_contents.append(text)
            except Exception as e:
                logger.warning(f"Cannot read {l1_path}: {e}")
        if not layer_contents:
            console.print("  [red]No Level 1 docs available[/red]")
            return filepath
        combined = "\n\n---\n\n".join(layer_contents)
        console.print(f"  L0_ARCHITECTURE_OVERVIEW.md ({len(level1_files)} layers, {len(combined)} chars)...", end=" ")
        try:
            result = self._llm_call(LEVEL0_PROMPT, combined, max_tokens=4096)
            title = "# Architecture Overview\n\n"
            self._save(filepath, title + result, f"Level 0 | Layers: {', '.join(level1_files.keys())}")
            console.print("[green]OK[/green]")
        except Exception as e:
            console.print(f"[red]FAIL: {e}[/red]")
            self.stats["failed"] += 1
        return filepath


# -- Main ---

def load_blocks(cfg: dict) -> dict:
    custom = cfg.get("synthesis", {}).get("blocks", {})
    blocks = dict(DEFAULT_BLOCKS)
    for name, bdef in custom.items():
        if name in blocks:
            blocks[name]["path_patterns"] = bdef.get("path_patterns", blocks[name]["path_patterns"])
            if "label" in bdef:
                blocks[name]["label"] = bdef["label"]
            if "description" in bdef:
                blocks[name]["description"] = bdef["description"]
        else:
            blocks[name] = bdef
    if "other" in blocks:
        other = blocks.pop("other")
        blocks["other"] = other
    return blocks


def show_classification(classification: dict, blocks: dict):
    table = Table(title="Document classification")
    table.add_column("Block", style="bold")
    table.add_column("Module", style="cyan")
    table.add_column("Docs", justify="right")
    table.add_column("Total size", justify="right")
    total_docs = 0
    for block_name in sorted(classification.keys()):
        modules = classification[block_name]
        label = blocks.get(block_name, {}).get("label", block_name)
        first = True
        for module_name in sorted(modules.keys()):
            doc_paths = modules[module_name]
            size = sum(p.stat().st_size for p in doc_paths)
            block_display = f"{label}" if first else ""
            table.add_row(block_display, module_name, str(len(doc_paths)), f"{size // 1024}KB")
            total_docs += len(doc_paths)
            first = False
    console.print(table)
    console.print(f"\n  Total: {total_docs} codex docs across {len(classification)} blocks")


def show_plan(classification: dict, blocks: dict):
    l2_count = sum(len(modules) for modules in classification.values())
    l1_count = len(classification)
    console.print(f"\n[bold]Synthesis plan:[/bold]")
    console.print(f"  Level 2: {l2_count} module docs")
    console.print(f"  Level 1: {l1_count} layer overviews")
    console.print(f"  Level 0: 1 architecture overview")
    console.print(f"  Total LLM calls: ~{l2_count + l1_count + 1}")
    console.print(f"  Estimated time: ~{(l2_count + l1_count + 1) * 5}s (with rate limiting)")
    console.print(f"\n  Output directory: {SYNTH_DIR}/")


def main():
    parser = argparse.ArgumentParser(description="Hierarchical documentation synthesis")
    parser.add_argument("--dry-run", "-n", action="store_true", help="Show classification + plan only")
    parser.add_argument("--classify", action="store_true", help="Only classify docs into blocks")
    parser.add_argument("--level", type=int, choices=[0, 1, 2], help="Build up to this level (default: all)")
    parser.add_argument("--force", "-f", action="store_true", help="Rebuild even if files exist")
    parser.add_argument("--config", "-c", default="config.yaml")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_path=False)],
    )
    for lib in ("httpx", "openai", "chromadb"):
        logging.getLogger(lib).setLevel(logging.WARNING)

    from src.config import load_config
    cfg = load_config(args.config)
    blocks = load_blocks(cfg)

    console.print("[bold blue]Classifying codex docs...[/bold blue]")
    classification = classify_all_docs(blocks)

    if not classification:
        console.print("[yellow]No codex_*.md files found in context/docs/[/yellow]")
        console.print("Run the codex agent first: python run.py --agent codex --skip-ingest")
        sys.exit(0)

    show_classification(classification, blocks)

    if args.classify:
        sys.exit(0)

    show_plan(classification, blocks)

    if args.dry_run:
        console.print("\n[dim]Dry run -- no files generated. Remove --dry-run to proceed.[/dim]")
        sys.exit(0)

    defaults = cfg.get("_defaults", {})
    if not defaults.get("api_base_url") or not defaults.get("api_key"):
        console.print("[red]API_BASE_URL and API_KEY required in .env[/red]")
        sys.exit(1)

    from src.client import ResilientClient
    from src.config import get_model_for_agent
    client = ResilientClient(
        api_key=defaults["api_key"],
        base_url=defaults["api_base_url"],
        max_retries=defaults.get("retry_max_attempts", 8),
    )
    model = get_model_for_agent(cfg, "codex")
    synth = Synthesizer(client, model, blocks, force=args.force)

    target = args.level if args.level is not None else 0
    level2_files = synth.build_level2(classification)
    if target <= 1:
        level1_files = synth.build_level1(level2_files)
        if target == 0:
            synth.build_level0(level1_files)

    console.print(f"\n[bold green]=== Synthesis complete ===[/bold green]")
    console.print(f"  LLM calls: {synth.stats['llm_calls']}")
    console.print(f"  Skipped (already exist): {synth.stats['skipped']}")
    console.print(f"  Failed: {synth.stats['failed']}")
    console.print(f"\n  Output: {SYNTH_DIR}/")

    if SYNTH_DIR.exists():
        files = sorted(SYNTH_DIR.glob("*.md"))
        l0 = [f for f in files if f.name.startswith("L0_")]
        l1 = [f for f in files if f.name.startswith("L1_")]
        l2 = [f for f in files if f.name.startswith("L2_")]
        console.print(f"  Level 0: {len(l0)} file(s)")
        for f in l0:
            console.print(f"    {f.name} ({f.stat().st_size // 1024}KB)")
        console.print(f"  Level 1: {len(l1)} file(s)")
        for f in l1:
            console.print(f"    {f.name} ({f.stat().st_size // 1024}KB)")
        console.print(f"  Level 2: {len(l2)} file(s)")

    console.print(f"\n  Next: python run.py --ingest  (to index synthesis docs into RAG)")


if __name__ == "__main__":
    main()
