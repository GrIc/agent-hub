#!/usr/bin/env python3
"""
synthesize.py -- Hierarchical documentation synthesis with weighted prompts.

Reads all codex docs and produces a dynamic multi-level documentation pyramid:

  L0  -- ARCHITECTURE_OVERVIEW.md         (1 file, the big picture)
  L1  -- {block}_OVERVIEW.md              (1 per block)
  L2+ -- {block}_{seg1}.md               (intermediate levels, dynamic)
  ...
  LN  -- {block}_{seg1}_{seg2}_..._{segN} (deepest level, 1 per module)

The number of intermediate levels is determined automatically by the depth
of the module name hierarchy within each block. The name segments come directly
from the codex doc filenames:

  codex_JAVA_mj_src_com_example_rest_controller.md
      -> block=backend, segments=[JAVA, mj, src, com, example, rest, controller]
      -> LN_backend_JAVA_mj_src_com_example_rest_controller.md   (deepest)
      -> ...
      -> L2_backend_JAVA.md
      -> L1_backend_OVERVIEW.md
      -> L0_ARCHITECTURE_OVERVIEW.md

Weighting: at every aggregation level, child sections are annotated with their
relative importance (descendant codex-doc count + KB), sorted heavy-first, and
the LLM is explicitly instructed to allocate coverage proportionally.

  JAVA  [weight: major | 87 sub-module(s) | 42 KB]   -> covered in depth
  thirdparty  [weight: minor | 1 sub-module(s) | 3 KB] -> mentioned briefly

Build order: bottom-up (deepest -> L1 -> L0).

Usage:
    python synthesize.py --dry-run            # Show classification + plan
    python synthesize.py --classify           # Only classify docs into blocks
    python synthesize.py --min-level 2        # Stop at level 2 (don't build L1/L0)
    python synthesize.py                      # Build all levels
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
logger  = logging.getLogger(__name__)

DOCS_DIR  = Path("context/docs")
SYNTH_DIR = DOCS_DIR / "synthesis"


# ---------------------------------------------------------------------------
# Block definitions
# ---------------------------------------------------------------------------

# ── Generic DEFAULT_BLOCKS for synthesize.py ──
# Replace the DEFAULT_BLOCKS dict in synthesize.py with this.
# These patterns are technology-agnostic and cover common project layouts.

DEFAULT_BLOCKS = {
    "tests": {
        "label": "Tests",
        "description": "Unit tests, integration tests, test utilities",
        "path_patterns": [
            "/test/", "/tests/", "/__tests__/",
            ".test.", ".spec.", "_test.", "_spec.",
            "Test.java", "Spec.js", "test_", "tests_",
        ],
    },
    "database": {
        "label": "Database",
        "description": "SQL scripts, schema definitions, migrations, data model, ORM",
        "path_patterns": [
            ".sql", "/migrations/", "/ddl/", "/schema/",
            "/models/", "/entities/", "/repositories/",
            "sql_", "_sql_", "migration_",
        ],
    },
    "frontend": {
        "label": "Frontend",
        "description": "JavaScript, TypeScript, HTML, CSS, web components, UI",
        "path_patterns": [
            "/js/", "/ts/", "/css/", "/html/", "/webapp/",
            "/components/", "/views/", "/pages/", "/layouts/",
            "/static/", "/public/", "/assets/",
            ".js_", ".ts_", ".jsx_", ".tsx_", ".vue_",
            ".html_", ".css_", ".scss_",
        ],
    },
    "backend": {
        "label": "Backend",
        "description": "Server-side code, business logic, API, services",
        "path_patterns": [
            ".java", ".py_", ".go_", ".rs_", ".rb_", ".php_",
            "/src/", "/lib/", "/pkg/", "/internal/",
            "/services/", "/controllers/", "/handlers/",
            "/api/", "/routes/", "/middleware/",
            "/com/", "/org/", "/net/",
        ],
    },
    "other": {
        "label": "Other",
        "description": "Configuration, scripts, infrastructure, documentation, misc",
        "path_patterns": [],  # catch-all
    },
}


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

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


def extract_segments(doc_path: Path) -> list[str]:
    """
    Extract path segments from a codex doc filename.

      codex_JAVA_mj_src_com_example_rest_controller.md
          -> ["JAVA", "mj", "src", "com", "example", "rest", "controller"]
    """
    stem  = doc_path.stem
    clean = re.sub(r"^codex_", "", stem)
    clean = re.sub(r"_\d{8}_\d{6}$", "", clean)   # strip old timestamp suffix
    return [s for s in clean.split("_") if s]


def classify_all_docs(blocks: dict) -> dict:
    """
    Classify all codex docs.

    Returns:
        {block_name: {segments_tuple: [Path, ...]}}
    """
    docs = sorted(DOCS_DIR.glob("codex_*.md"))
    if not docs:
        return {}

    result: dict[str, dict[tuple, list]] = defaultdict(lambda: defaultdict(list))
    for doc in docs:
        block    = classify_doc(doc, blocks)
        segments = tuple(extract_segments(doc))
        result[block][segments].append(doc)

    return {b: dict(m) for b, m in result.items()}


# ---------------------------------------------------------------------------
# Weight helpers
# ---------------------------------------------------------------------------

def _count_descendants(segments: tuple, classification_block: dict) -> int:
    """Count how many leaf codex docs fall under a given segment prefix."""
    count = 0
    n = len(segments)
    for segs, paths in classification_block.items():
        if segs[:n] == segments:
            count += len(paths)
    return count


def _kb_of_file(path: Path) -> int:
    try:
        return max(1, path.stat().st_size // 1024)
    except OSError:
        return 1


def _weight_label(score: float) -> str:
    if score >= 0.4:
        return "major"
    elif score >= 0.1:
        return "normal"
    else:
        return "minor"


def _compute_child_weights(
    child_files: dict[tuple, Path],
    classification_block: dict | None,
) -> dict[tuple, dict]:
    """
    For each child compute leaf_count, kb, combined score (0..1), weight label.

    Score = 0.7 * (count / max_count) + 0.3 * (kb / max_kb)
    This makes descendant richness the primary signal and file size secondary.
    """
    stats: dict[tuple, dict] = {}
    for segs, path in child_files.items():
        leaf_count = (
            _count_descendants(segs, classification_block)
            if classification_block is not None
            else 1
        )
        stats[segs] = {"leaf_count": max(leaf_count, 1), "kb": _kb_of_file(path)}

    max_count = max(s["leaf_count"] for s in stats.values())
    max_kb    = max(s["kb"]         for s in stats.values())

    for segs in stats:
        c  = stats[segs]["leaf_count"]
        kb = stats[segs]["kb"]
        score = (c / max_count) * 0.7 + (kb / max_kb) * 0.3
        stats[segs]["score"]  = score
        stats[segs]["weight"] = _weight_label(score)

    return stats


# ---------------------------------------------------------------------------
# LLM Prompts
# ---------------------------------------------------------------------------

DEEPEST_LEVEL_PROMPT = """\
You are a senior software architect writing internal documentation.

Below are detailed codex scan docs for files in the **{module}** module \
({block} layer).

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

WEIGHTED_INTERMEDIATE_PROMPT = """\
You are a senior software architect writing internal documentation.

Below are documentation summaries for all sub-modules of **{module}** \
({block} layer).

IMPORTANT -- coverage weighting:
Each section header shows [weight: major|normal|minor | N sub-module(s) | X KB].
This reflects the relative importance of each sub-module within this group,
based on the number of descendant modules and code volume.

Allocation rules:
- **major**: large, critical sub-module -- cover in depth (several paragraphs).
- **normal**: moderately significant -- summarise concisely (1-2 paragraphs).
- **minor**: small or peripheral -- mention briefly (1-2 sentences).
A major sub-module should receive 3-5x more narrative space than a minor one.

Produce a GROUP OVERVIEW ({min_words}-{max_words} words) that covers:
1. **Group purpose**: What this group of modules does overall (2-4 sentences)
2. **Sub-module map**: Table of all sub-modules with weight, role, key classes
3. **Internal dependencies**: How sub-modules depend on each other
4. **External interfaces**: How this group connects to other parts of the system
5. **Data flow**: How data moves through this group
6. **Architecture patterns**: Design patterns or structural choices in this group

Write in English. Be factual. Cite specific class/module names.

GROUNDING RULES:
- ONLY describe modules, classes, patterns, and technologies that are EXPLICITLY
  mentioned in the sub-module summaries below. Do not infer or extrapolate.
- If a sub-module summary does not mention a specific class or pattern, do NOT
  add it to the group overview. Omission is better than invention.
- Every class name, module name, and technology you cite must appear verbatim
  in at least one of the input summaries.
- If the input summaries are thin or vague, produce a proportionally shorter overview.

Sub-module summaries (sorted by importance, heaviest first):
"""

WEIGHTED_LEVEL1_PROMPT = """\
You are a senior software architect writing internal documentation.

Below are module-level summaries for the **{block}** layer of the application.

IMPORTANT -- coverage weighting:
Each section header shows [weight: major|normal|minor | N sub-module(s) | X KB].
This reflects the relative importance of each top-level module in this layer.

Allocation rules:
- **major**: core module -- cover in depth (several paragraphs).
- **normal**: significant but secondary -- summarise concisely (1-2 paragraphs).
- **minor**: thin or peripheral module -- mention briefly (1-2 sentences only).
Allocate narrative space proportionally.

Produce a LAYER OVERVIEW (800-1500 words) that covers:
1. **Layer purpose**: What the {block} layer does overall (3-5 sentences)
2. **Module map**: Table of all modules with weight, role, key classes
3. **Architecture patterns**: How modules are organised, design patterns used
4. **Inter-module dependencies**: How modules within this layer depend on each other
5. **External interfaces**: How this layer connects to other layers
6. **Data flow**: How data moves through this layer
7. **Key technologies**: Frameworks, libraries, tools specific to this layer

Write in English. Be factual.

GROUNDING RULES:
- ONLY describe modules, classes, frameworks, and patterns that are EXPLICITLY
  mentioned in the module summaries below. Do not infer or extrapolate.
- If a module summary does not mention a specific technology, class, or pattern,
  do NOT include it in the layer overview.
- Every name you cite must appear verbatim in at least one input summary.
- If information is sparse, produce a shorter overview. Do not pad with guesses.

Module summaries (sorted by importance, heaviest first):
"""

LEVEL0_PROMPT = """\
You are a senior software architect producing the definitive architecture \
document for a development team.

Below are overviews of each architectural layer of the application.

Produce an ARCHITECTURE OVERVIEW (1500-2500 words) that covers:
1. **System overview**: What is this application? (5-8 sentences)
2. **Technology stack**: Languages, frameworks, databases, infrastructure (table)
3. **Architecture diagram** (text): Layers, responsibilities, how they connect
4. **Layer summary**: Table with each layer, purpose, module count, key tech
5. **Cross-layer data flow**: How a typical request flows end-to-end
6. **Integration points**: External systems, APIs, services
7. **Key architectural patterns**: Patterns observed across the whole system
8. **Data model overview**: Main business entities and their relationships
9. **Entry points**: All the ways requests/data enter the system
10. **Known gaps**: What the documentation doesn't cover

Write in English. Be precise. Reference specific module and class names.

GROUNDING RULES:
- ONLY describe layers, modules, patterns, and technologies that are EXPLICITLY
  mentioned in the layer overviews below. This is a SYNTHESIS, not speculation.
- If a layer overview does not mention a specific integration, pattern, or technology,
  do NOT include it in the architecture overview. Fabricated content will corrupt
  the documentation system used by all development agents.
- Every module name, class name, framework, and technology you cite must appear
  verbatim in at least one input layer overview.
- For the "Known gaps" section, list things the overviews do NOT cover — do not
  invent coverage that doesn't exist.
  
Layer overviews:
"""

# Condense oversized docs before feeding them into a higher synthesis level
CONDENSE_THRESHOLD = 8_000   # chars: above this, condense before passing to LLM
CONDENSE_TARGET    = 6_000   # target size after condensation

CONDENSE_PROMPT = """\
You are a technical documentation editor.
The document below is a detailed codex scan of a source module. \
It is too long to be used directly in a higher-level synthesis.

Produce a CONDENSED VERSION (target: {target_words} words) that preserves:
- Every class name, interface, and enum with its role (1 sentence each)
- Every public method / function that is an entry point or cross-module boundary
- All external dependencies (imports, injected services, called APIs)
- Data structures / schemas owned by this module
- Any non-obvious architectural pattern or constraint

Strip: inline code examples, repetitive getters/setters, test scaffolding \
details, lengthy prose that duplicates what the class names already convey.

Write in English. Be dense and factual -- this feeds an architecture synthesis \
engine.

GROUNDING RULES:
- ONLY preserve information that is explicitly stated in the document below.
- NEVER add classes, methods, patterns, or technologies not mentioned in the source.
- If something is unclear in the source, omit it rather than guess.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def segments_to_module_name(segments: tuple) -> str:
    return "_".join(segments) if segments else "root"


def synth_filename(block: str, segments: tuple, depth: int) -> str:
    """
    Build the synthesis filename.

      (backend, (JAVA, managers), 4) -> L4_backend_JAVA_managers.md
      (backend, (JAVA,),          3) -> L3_backend_JAVA.md
      (backend, (),                 1) -> L1_backend_OVERVIEW.md  (handled separately)
    """
    seg_str = ("_" + "_".join(segments)) if segments else ""
    return f"L{depth}_{block}{seg_str}.md"


def strip_header(text: str) -> str:
    """Remove the auto-generated header block from a synthesis doc."""
    return re.sub(r"^>.*?\n---\n\n", "", text, flags=re.DOTALL)


def _weighted_section(
    segs: tuple,
    path: Path,
    stats: dict,
    condense_fn,
) -> str:
    """
    Read a child file and prepend its weighted header.

    Header format:
        ### Module: JAVA  [weight: major | 87 sub-module(s) | 42 KB]
    """
    s            = stats[segs]
    module_name  = segments_to_module_name(segs) if segs else path.stem
    weight_label = s["weight"]
    leaf_count   = s["leaf_count"]
    kb           = s["kb"]

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        text = strip_header(text)
        if len(text) > CONDENSE_THRESHOLD:
            text = condense_fn(text, path.name)
    except Exception as e:
        logger.warning(f"Cannot read {path}: {e}")
        text = "[unreadable]"

    header = (
        f"### Module: {module_name}"
        f"  [weight: {weight_label} | {leaf_count} sub-module(s) | {kb} KB]\n"
    )
    return header + text


# ---------------------------------------------------------------------------
# Synthesis engine
# ---------------------------------------------------------------------------

class Synthesizer:
    """
    Dynamic hierarchical documentation synthesizer with weighted prompts.

    At every aggregation level each child section receives:
      1. A header annotating its relative importance (leaf_count, KB, weight label)
      2. Position near the top of the prompt (heaviest first)
    The LLM is explicitly told to allocate coverage proportionally, so parent level
    (100 descendants) dominates the overview relative to thirdparty (1 descendant).
    """

    def __init__(self, client, model: str, blocks: dict, force: bool = False):
        self.client = client
        self.model  = model
        self.blocks = blocks
        self.force  = force
        self.stats  = {"llm_calls": 0, "skipped": 0, "failed": 0, "condensed": 0}

    # -- LLM + IO --

    def _llm_call(self, system: str, content: str, max_tokens: int = 4096) -> str:
        if len(content) > 30000:
            content = content[:30000] + "\n\n[... truncated]"
        self.stats["llm_calls"] += 1
        result = self.client.chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": content},
            ],
            model=self.model,
            temperature=0.2,
            max_tokens=max_tokens,
            complete=True,
        )
        time.sleep(2)
        return result

    def _condense(self, text: str, source_name: str) -> str:
        target_words = CONDENSE_TARGET // 5
        console.print(
            f"\n    [dim]Condensing {source_name} "
            f"({len(text) // 1024}KB -> ~{CONDENSE_TARGET // 1024}KB)...[/dim]",
            end=" ",
        )
        try:
            condensed = self._llm_call(
                system=CONDENSE_PROMPT.format(target_words=target_words),
                content=text,
                max_tokens=2048,
            )
            console.print("[dim]done[/dim]")
            logger.info(f"[Condense] {source_name}: {len(text)} -> {len(condensed)} chars")
            self.stats["condensed"] += 1
            return condensed
        except Exception as e:
            logger.warning(f"[Condense] Failed for {source_name}: {e} -- truncating")
            return text[:CONDENSE_TARGET] + "\n[... truncated]"

    def _save(self, filepath: Path, content: str, header_info: str = ""):
        filepath.parent.mkdir(parents=True, exist_ok=True)
        header = (
            f"> Auto-generated by synthesize.py on "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"> {header_info}\n"
            f"> Re-generate: `python synthesize.py`\n\n---\n\n"
        )
        filepath.write_text(header + content, encoding="utf-8")

    # -- Weighted content assembly --

    def _assemble_weighted(
        self,
        child_files: dict[tuple, Path],
        classification_block: dict | None,
    ) -> tuple[str, dict]:
        """
        Build combined prompt content sorted heaviest-first with weight headers.

        Returns (combined_text, stats_dict).
        """
        stats = _compute_child_weights(child_files, classification_block)

        sorted_segs = sorted(
            child_files.keys(),
            key=lambda s: stats[s]["score"],
            reverse=True,
        )

        sections = [
            _weighted_section(
                segs=segs,
                path=child_files[segs],
                stats=stats,
                condense_fn=self._condense,
            )
            for segs in sorted_segs
        ]

        return "\n\n---\n\n".join(sections), stats

    def _weight_log(self, stats: dict, include_count: bool = False) -> str:
        """Format weight summary for console output."""
        parts = []
        for s in sorted(stats, key=lambda x: stats[x]["score"], reverse=True):
            name = segments_to_module_name(s) if s else "root"
            w    = stats[s]["weight"]
            if include_count:
                parts.append(f"{name}={w}({stats[s]['leaf_count']})")
            else:
                parts.append(f"{name}={w}")
        return ", ".join(parts)

    # -- Deepest level: raw codex docs -> first synthesis nodes --

    def _build_deepest(
        self,
        block: str,
        segments_map: dict[tuple, list[Path]],
    ) -> dict[tuple, Path]:
        """One synthesis file per unique segment tuple, aggregating its codex docs."""
        block_label = self.blocks.get(block, {}).get("label", block)
        max_depth   = max((len(s) for s in segments_map.keys()), default=1)
        depth_label = max(2, max_depth + 2)
        result: dict[tuple, Path] = {}

        for segments in sorted(segments_map.keys()):
            doc_paths   = segments_map[segments]
            module_name = segments_to_module_name(segments)
            filename    = synth_filename(block, segments, depth_label)
            filepath    = SYNTH_DIR / filename

            if filepath.exists() and not self.force:
                console.print(f"  [dim]Skip {filename} (exists)[/dim]")
                self.stats["skipped"] += 1
                result[segments] = filepath
                continue

            doc_contents = []
            for dp in doc_paths:
                try:
                    text = dp.read_text(encoding="utf-8", errors="replace")
                    if len(text) > CONDENSE_THRESHOLD:
                        text = self._condense(text, dp.name)
                    doc_contents.append(f"### Source: {dp.name}\n{text}")
                except Exception as e:
                    logger.warning(f"Cannot read {dp}: {e}")

            if not doc_contents:
                continue

            combined = "\n\n".join(doc_contents)
            prompt   = DEEPEST_LEVEL_PROMPT.format(
                module=module_name, block=block_label
            )

            console.print(
                f"  {filename} ({len(doc_paths)} source(s), {len(combined)} chars)...",
                end=" ",
            )
            try:
                result_text = self._llm_call(prompt, combined, max_tokens=2048)
                title = f"# {block_label} -- {module_name}\n\n"
                self._save(
                    filepath,
                    title + result_text,
                    f"Level {depth_label} | {block_label} | Module: {module_name}"
                    f" | Sources: {len(doc_paths)}",
                )
                console.print("[green]OK[/green]")
                result[segments] = filepath
            except Exception as e:
                console.print(f"[red]FAIL: {e}[/red]")
                self.stats["failed"] += 1

        return result

    # -- Roll-up: weighted intermediate levels --

    def _build_rollup_node(
        self,
        block: str,
        parent_segments: tuple,
        depth: int,
        child_files: dict[tuple, Path],
        classification_block: dict,
    ) -> Path | None:
        block_label = self.blocks.get(block, {}).get("label", block)
        module_name = (
            segments_to_module_name(parent_segments) if parent_segments else block_label
        )
        filename = synth_filename(block, parent_segments, depth)
        filepath = SYNTH_DIR / filename

        if filepath.exists() and not self.force:
            console.print(f"  [dim]Skip {filename} (exists)[/dim]")
            self.stats["skipped"] += 1
            return filepath

        combined, stats = self._assemble_weighted(child_files, classification_block)
        if not combined.strip():
            return None

        # Scale word-count target with number of children
        n         = len(child_files)
        min_words = min(400 + n * 60, 1200)
        max_words = min(600 + n * 80, 1400)

        prompt = WEIGHTED_INTERMEDIATE_PROMPT.format(
            module=module_name,
            block=block_label,
            min_words=min_words,
            max_words=max_words,
        )

        console.print(
            f"  {filename} ({n} children [{self._weight_log(stats)}], "
            f"{len(combined)} chars)...",
            end=" ",
        )
        try:
            result_text = self._llm_call(prompt, combined, max_tokens=2048)
            title = f"# {block_label} -- {module_name}\n\n"
            self._save(
                filepath,
                title + result_text,
                f"Level {depth} | {block_label} | Module: {module_name}"
                f" | Children: {n}",
            )
            console.print("[green]OK[/green]")
            return filepath
        except Exception as e:
            console.print(f"[red]FAIL: {e}[/red]")
            self.stats["failed"] += 1
            return None

    def _rollup(
        self,
        block: str,
        current_files: dict[tuple, Path],
        current_depth: int,
        classification_block: dict,
    ) -> dict[tuple, Path]:
        """
        Repeatedly group by (N-1)-segment prefix and build one weighted synthesis
        file per group, until all keys have length <= 1.
        """
        while True:
            if all(not segs for segs in current_files.keys()):
                break
            if all(len(segs) <= 1 for segs in current_files.keys()):
                break

            groups: dict[tuple, dict[tuple, Path]] = defaultdict(dict)
            for segs, path in current_files.items():
                prefix = segs[:-1] if segs else ()
                groups[prefix][segs] = path

            next_files: dict[tuple, Path] = {}
            current_depth -= 1

            console.print(
                f"\n[bold blue]=== Level {current_depth}: "
                f"{block} -- {len(groups)} group(s) ===[/bold blue]"
            )

            for prefix, children in sorted(groups.items()):
                # Single child that IS the prefix -- carry it up unchanged
                if len(children) == 1 and list(children.keys())[0] == prefix:
                    next_files[prefix] = list(children.values())[0]
                    continue

                built = self._build_rollup_node(
                    block=block,
                    parent_segments=prefix,
                    depth=current_depth,
                    child_files=children,
                    classification_block=classification_block,
                )
                if built:
                    next_files[prefix] = built
                else:
                    next_files.update(children)

            current_files = next_files

        return current_files

    # -- L1: weighted layer overview --

    def build_level1(
        self,
        block_top_files: dict[str, dict[tuple, Path]],
        classification: dict,
    ) -> dict[str, Path]:
        console.print("\n[bold blue]=== Level 1: Layer overviews ===[/bold blue]")
        level1_files: dict[str, Path] = {}

        for block_name in sorted(block_top_files.keys()):
            top_files = block_top_files[block_name]
            if not top_files:
                continue

            block_label = self.blocks.get(block_name, {}).get("label", block_name)
            block_desc  = self.blocks.get(block_name, {}).get("description", "")
            filename    = f"L1_{block_name}_OVERVIEW.md"
            filepath    = SYNTH_DIR / filename

            if filepath.exists() and not self.force:
                console.print(f"  [dim]Skip {filename} (exists)[/dim]")
                level1_files[block_name] = filepath
                self.stats["skipped"] += 1
                continue

            combined, stats = self._assemble_weighted(
                top_files, classification.get(block_name, {})
            )
            if not combined.strip():
                continue

            prompt = WEIGHTED_LEVEL1_PROMPT.format(block=block_label)

            console.print(
                f"  {filename} ({len(top_files)} module(s) "
                f"[{self._weight_log(stats, include_count=True)}], "
                f"{len(combined)} chars)...",
                end=" ",
            )
            try:
                result = self._llm_call(prompt, combined, max_tokens=3072)
                title  = f"# {block_label} -- Overview\n\n{block_desc}\n\n"
                self._save(
                    filepath,
                    title + result,
                    f"Level 1 | {block_label} | Modules: {len(top_files)}",
                )
                level1_files[block_name] = filepath
                console.print("[green]OK[/green]")
            except Exception as e:
                console.print(f"[red]FAIL: {e}[/red]")
                self.stats["failed"] += 1

        return level1_files

    # -- L0: architecture overview --

    def build_level0(self, level1_files: dict[str, Path]) -> Path:
        console.print("\n[bold blue]=== Level 0: Architecture overview ===[/bold blue]")
        filepath = SYNTH_DIR / "L0_ARCHITECTURE_OVERVIEW.md"

        if filepath.exists() and not self.force:
            console.print("  [dim]Skip L0_ARCHITECTURE_OVERVIEW.md (exists)[/dim]")
            self.stats["skipped"] += 1
            return filepath

        layer_contents = []
        for block_name, l1_path in sorted(level1_files.items()):
            try:
                text = l1_path.read_text(encoding="utf-8", errors="replace")
                layer_contents.append(strip_header(text))
            except Exception as e:
                logger.warning(f"Cannot read {l1_path}: {e}")

        if not layer_contents:
            console.print("  [red]No Level 1 docs available[/red]")
            return filepath

        combined = "\n\n---\n\n".join(layer_contents)
        console.print(
            f"  L0_ARCHITECTURE_OVERVIEW.md "
            f"({len(level1_files)} layers, {len(combined)} chars)...",
            end=" ",
        )
        try:
            result = self._llm_call(LEVEL0_PROMPT, combined, max_tokens=4096)
            self._save(
                filepath,
                "# Architecture Overview\n\n" + result,
                f"Level 0 | Layers: {', '.join(level1_files.keys())}",
            )
            console.print("[green]OK[/green]")
        except Exception as e:
            console.print(f"[red]FAIL: {e}[/red]")
            self.stats["failed"] += 1

        return filepath

    # -- Main entry point --

    def build_all(self, classification: dict, min_level: int = 0):
        """
        Full bottom-up synthesis pass.

        classification : {block: {segments_tuple: [doc_paths]}}
        min_level      : 0=all, 1=skip L0, 2=skip L1+L0
        """
        # Phase 1 -- deepest level
        block_deepest: dict[str, dict[tuple, Path]] = {}
        for block_name in sorted(classification.keys()):
            segments_map = classification[block_name]
            max_seg_len  = max((len(s) for s in segments_map.keys()), default=1)
            depth_label  = max(2, max_seg_len + 2)

            console.print(
                f"\n[bold blue]=== Deepest level (L{depth_label}): "
                f"{block_name} -- {len(segments_map)} module(s) ===[/bold blue]"
            )
            block_deepest[block_name] = self._build_deepest(block_name, segments_map)

        if min_level > 2:
            return

        # Phase 2 -- dynamic roll-ups
        block_top: dict[str, dict[tuple, Path]] = {}
        for block_name, deepest_files in block_deepest.items():
            max_seg_len    = max((len(s) for s in deepest_files.keys()), default=1)
            starting_depth = max(2, max_seg_len + 2)

            if max_seg_len <= 1:
                block_top[block_name] = deepest_files
            else:
                block_top[block_name] = self._rollup(
                    block=block_name,
                    current_files=deepest_files,
                    current_depth=starting_depth,
                    classification_block=classification.get(block_name, {}),
                )

        if min_level >= 1:
            return

        # Phase 3 -- weighted L1
        level1_files = self.build_level1(block_top, classification)

        # Phase 4 -- L0
        if min_level == 0:
            self.build_level0(level1_files)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_blocks(cfg: dict) -> dict:
    custom = cfg.get("synthesis", {}).get("blocks", {})
    blocks = dict(DEFAULT_BLOCKS)
    for name, bdef in custom.items():
        if name in blocks:
            blocks[name]["path_patterns"] = bdef.get(
                "path_patterns", blocks[name]["path_patterns"]
            )
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
    table.add_column("Block",             style="bold")
    table.add_column("Module (segments)", style="cyan")
    table.add_column("Docs",  justify="right")
    table.add_column("Total size", justify="right")
    total_docs = 0
    for block_name in sorted(classification.keys()):
        modules = classification[block_name]
        label   = blocks.get(block_name, {}).get("label", block_name)
        first   = True
        for segments in sorted(modules.keys()):
            doc_paths     = modules[segments]
            size          = sum(p.stat().st_size for p in doc_paths)
            block_display = label if first else ""
            table.add_row(
                block_display,
                segments_to_module_name(segments),
                str(len(doc_paths)),
                f"{size // 1024}KB",
            )
            total_docs += len(doc_paths)
            first = False
    console.print(table)
    console.print(f"\n  Total: {total_docs} codex docs across {len(classification)} blocks")


def show_plan(classification: dict, blocks: dict):
    console.print("\n[bold]Synthesis plan (dynamic levels + weighted prompts):[/bold]")
    total_llm = 0
    for block_name in sorted(classification.keys()):
        modules     = classification[block_name]
        label       = blocks.get(block_name, {}).get("label", block_name)
        max_depth   = max((len(s) for s in modules.keys()), default=1)
        depth_label = max(2, max_depth + 2)

        level_counts = []
        segs_set = set(modules.keys())
        for length in range(max_depth, 0, -1):
            prefixes = set(s[:length] for s in segs_set if len(s) >= length)
            level_counts.append((depth_label, len(prefixes)))
            depth_label -= 1

        block_calls = sum(c for _, c in level_counts) + 1
        total_llm  += block_calls

        console.print(
            f"\n  [bold]{label}[/bold] ({len(modules)} modules, max depth={max_depth}):"
        )
        for lvl, count in level_counts:
            console.print(f"    L{lvl}: {count} file(s)")
        console.print(f"    L1:  1 file (weighted overview)")

    total_llm += 1  # L0
    console.print(f"\n  L0: 1 architecture overview")
    console.print(f"\n  Estimated LLM calls: ~{total_llm}")
    console.print(f"  Estimated time     : ~{total_llm * 5}s (at 2s pacing)")
    console.print(f"\n  Output directory   : {SYNTH_DIR}/")


def main():
    parser = argparse.ArgumentParser(
        description="Hierarchical documentation synthesis "
                    "(dynamic levels + weighted prompts)"
    )
    parser.add_argument("--dry-run",   "-n", action="store_true",
                        help="Show classification + plan only")
    parser.add_argument("--classify",        action="store_true",
                        help="Only classify docs into blocks")
    parser.add_argument("--min-level", type=int, default=0,
                        help="Stop building above this level "
                             "(0=all, 1=skip L0, 2=skip L1+L0)")
    parser.add_argument("--force",     "-f", action="store_true",
                        help="Rebuild even if files exist")
    parser.add_argument("--config",    "-c", default="config.yaml")
    parser.add_argument("--verbose",   "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_path=False)],
    )
    for lib in ("httpx", "openai", "chromadb"):
        logging.getLogger(lib).setLevel(logging.WARNING)

    from src.config import load_config
    cfg    = load_config(args.config)
    blocks = load_blocks(cfg)

    console.print("[bold blue]Classifying codex docs...[/bold blue]")
    classification = classify_all_docs(blocks)

    if not classification:
        console.print("[yellow]No codex_*.md files found in context/docs/[/yellow]")
        console.print(
            "Run the codex agent first: python run.py --agent codex --skip-ingest"
        )
        sys.exit(0)

    show_classification(classification, blocks)

    if args.classify:
        sys.exit(0)

    show_plan(classification, blocks)

    if args.dry_run:
        console.print(
            "\n[dim]Dry run -- no files generated. "
            "Remove --dry-run to proceed.[/dim]"
        )
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

    synth.build_all(classification, min_level=args.min_level)

    console.print(f"\n[bold green]=== Synthesis complete ===[/bold green]")
    console.print(f"  LLM calls     : {synth.stats['llm_calls']}")
    console.print(f"  Condensed docs: {synth.stats['condensed']}")
    console.print(f"  Skipped       : {synth.stats['skipped']}")
    console.print(f"  Failed        : {synth.stats['failed']}")
    console.print(f"\n  Output: {SYNTH_DIR}/")

    if SYNTH_DIR.exists():
        files    = sorted(SYNTH_DIR.glob("*.md"))
        by_level: dict[str, list] = defaultdict(list)
        for f in files:
            m   = re.match(r"^(L\d+)_", f.name)
            lvl = m.group(1) if m else "?"
            by_level[lvl].append(f)
        for lvl in sorted(by_level.keys(), reverse=True):
            flist = by_level[lvl]
            console.print(f"  {lvl}: {len(flist)} file(s)")
            if lvl in ("L0", "L1"):
                for f in flist:
                    console.print(f"    {f.name} ({f.stat().st_size // 1024}KB)")

    console.print(f"\n  Next: python run.py --ingest  (to index synthesis docs into RAG)")


if __name__ == "__main__":
    main()