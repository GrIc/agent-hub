#!/usr/bin/env python3
"""
build_graph.py — Thin orchestrator for GraphRAG v2 pipeline.

This is a thin driver that coordinates the language-agnostic GraphRAG v2 pipeline:
  1. Topology layer (always) — filesystem + git graph
  2. Structural layer (if extension maps to supported language) — AST extraction via tree-sitter queries
  3. Resolution pass — heuristic FQN resolution for calls edges
  4. Hub dampening — reduce noise from high-degree hub nodes
  5. Optional enrichment — LLM semantic enrichment of Class/Service nodes

Incremental updates are handled by delete_for_file() for changed files only.
No LLM calls during structural extraction — only for optional enrichment phase.

Usage:
    python build_graph.py                      # Full incremental build
    python build_graph.py --force              # Full rebuild from scratch
    python build_graph.py --enrich             # Run enrichment only on existing graph
    python build_graph.py --enrich-only        # Enrichment only, no structural changes
    python build_graph.py --stats              # Show graph statistics
    python build_graph.py --dry-run            # Preview changes
"""

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from src.client import ResilientClient
from src.config import load_config, get_model_for_agent, get_agent_temperature
from src.graph.enricher import enrich_all
from src.graph.extractor import extract_from_file
from src.graph.parsers import get_parser
from src.graph.resolver import resolve_edges, ResolutionStats
from src.graph.store import GraphStore
from src.graph.topology import (
    emit_directory_tree,
    emit_file_nodes,
    emit_file_contains_edges,
    emit_co_change_edges,
)

console = Console()
logger = logging.getLogger(__name__)

STATE_FILE = Path(".graphdb") / "build_state.json"


def _load_state() -> dict:
    """Load build state for incremental updates."""
    if STATE_FILE.exists():
        try:
            import json
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_state(state: dict) -> None:
    """Save build state for incremental updates."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    import json
    STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _file_hash(path: Path) -> str:
    """Quick content hash for change detection."""
    try:
        import hashlib
        return hashlib.md5(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _discover_files(workspace: Path, extensions: dict, unknown_policy: str) -> list[tuple[Path, Optional[str]]]:
    """Discover all files in workspace and map to language if supported.
    
    Returns list of (file_path, language) where language is None for unsupported files.
    """
    files = []
    
    # Walk workspace
    for dirpath, dirnames, filenames in sorted(os.walk(workspace)):
        dirnames[:] = sorted([d for d in dirnames if not d.startswith(".")])
        
        for fname in sorted(filenames):
            if fname.startswith("."):
                continue
            
            full_path = Path(dirpath) / fname
            rel_path = full_path.relative_to(workspace)
            
            # Skip based on extension
            ext = full_path.suffix.lower()
            language = extensions.get(ext)
            
            # Apply unknown language policy
            if language is None:
                if unknown_policy == "skip":
                    continue
                # else: topology_only (language=None is fine)
            
            files.append((full_path, language))
    
    return files


def _emit_topology_layers(store: GraphStore, workspace: Path, config: dict) -> None:
    """Emit topology layer: directory tree, file nodes, and co-change edges."""
    graph_cfg = config.get("graph", {})
    
    # Emit directory tree (Module nodes and contains edges)
    dir_nodes, dir_edges = emit_directory_tree(str(workspace))
    for node in dir_nodes:
        store.upsert_node(
            id=node.id,
            type=node.type,
            name=node.name,
            file_path=node.file_path,
            line_start=node.line_start,
            line_end=node.line_end,
            metadata=node.metadata,
        )
    for edge in dir_edges:
        store.upsert_edge(
            source_id=edge.source_id,
            target_id=edge.target_id,
            relation=edge.relation,
            evidence_path=edge.evidence_path,
            evidence_line=edge.evidence_line,
            metadata=edge.metadata,
        )
    
    # Emit file nodes
    extensions_set = set(graph_cfg.get("extensions", {}).keys())
    unknown_policy = graph_cfg.get("unknown_language_policy", "topology_only")
    file_nodes = emit_file_nodes(
        str(workspace),
        extensions=extensions_set if unknown_policy != "skip" else None,
    )
    for node in file_nodes:
        store.upsert_node(
            id=node.id,
            type=node.type,
            name=node.name,
            file_path=node.file_path,
            line_start=node.line_start,
            line_end=node.line_end,
            metadata=node.metadata,
        )
    
    # Emit File → Module contains edges
    file_contains_edges = emit_file_contains_edges(str(workspace), file_nodes)
    for edge in file_contains_edges:
        store.upsert_edge(
            source_id=edge.source_id,
            target_id=edge.target_id,
            relation=edge.relation,
            evidence_path=edge.evidence_path,
            evidence_line=edge.evidence_line,
            metadata=edge.metadata,
        )
    
    # Emit co-change edges (requires git)
    try:
        co_edges = emit_co_change_edges(str(workspace))
        for edge in co_edges:
            store.upsert_edge(
                source_id=edge.source_id,
                target_id=edge.target_id,
                relation=edge.relation,
                evidence_path=edge.evidence_path,
                evidence_line=edge.evidence_line,
                metadata=edge.metadata,
            )
    except Exception as e:
        logger.warning("Could not compute co-change edges: %s", e)


def _process_file_with_structural_extraction(
    store: GraphStore,
    file_path: Path,
    language: str,
    queries_dir: str,
    config: dict,
) -> tuple[int, int]:
    """Process a single file with structural extraction if language is supported.
    
    Returns: (node_count, edge_count)
    """
    try:
        source_bytes = file_path.read_bytes()
    except OSError as e:
        logger.warning("Cannot read %s: %s", file_path, e)
        return 0, 0
    
    # Clean up old data for this file
    removed = store.delete_for_file(str(file_path))
    logger.debug("Removed %d nodes and %d edges for %s", 
                 removed["nodes"], removed["edges"], file_path)
    
    # Extract structural nodes/edges via tree-sitter queries
    nodes, edges = extract_from_file(
        file_path=str(file_path),
        source_bytes=source_bytes,
        language=language,
        queries_dir=queries_dir,
    )
    
    # Upsert nodes and edges
    for node in nodes:
        store.upsert_node(
            id=node.id,
            type=node.type,
            name=node.name,
            file_path=node.file_path,
            line_start=node.line_start,
            line_end=node.line_end,
            metadata=node.metadata,
        )
    
    for edge in edges:
        store.upsert_edge(
            source_id=edge.source_id,
            target_id=edge.target_id,
            relation=edge.relation,
            evidence_path=edge.evidence_path,
            evidence_line=edge.evidence_line,
            metadata=edge.metadata,
        )
    
    return len(nodes), len(edges)


def _apply_hub_dampening(store: GraphStore, config: dict) -> int:
    """Apply hub node dampening to reduce noise from high-degree nodes."""
    graph_cfg = config.get("graph", {})
    dampening_cfg = graph_cfg.get("hub_dampening", {})
    
    if not dampening_cfg.get("enabled", True):
        logger.info("Hub dampening disabled by config")
        return 0
    
    threshold = float(dampening_cfg.get("threshold", 0.20))
    factor = float(dampening_cfg.get("factor", 0.30))
    
    stats = resolve_edges.apply_hub_node_dampening(store, threshold=threshold, factor=factor)
    return stats.modified_edges


def _run_enrichment_phase(store: GraphStore, client: ResilientClient, config: dict) -> dict:
    """Run semantic enrichment on Class and Service nodes.
    
    Returns: enrichment stats dict
    """
    enricher_cfg = config.get("graph", {}).get("enricher", {})
    batch_size = enricher_cfg.get("batch_size", 10)
    
    stats = enrich_nodes_batch(store, client, config, batch_size=batch_size)
    return stats


def show_stats(store: GraphStore) -> None:
    """Display graph statistics with Rich tables."""
    stats = store.stats()

    console.print(f"\n[bold]Knowledge Graph Statistics[/bold]")
    console.print(f"  Nodes: {stats['nodes']}")
    console.print(f"  Edges: {stats['edges']}")
    console.print(f"  Connected components: {stats['connected_components']}")

    if stats["node_types"]:
        table = Table(title="Node Types")
        table.add_column("Type", style="cyan")
        table.add_column("Count", justify="right")
        for ntype, count in sorted(stats["node_types"].items(), key=lambda x: -x[1]):
            table.add_row(ntype, str(count))
        console.print(table)

    if stats["relation_types"]:
        table = Table(title="Relation Types")
        table.add_column("Relation", style="green")
        table.add_column("Count", justify="right")
        for rtype, count in sorted(stats["relation_types"].items(), key=lambda x: -x[1]):
            table.add_row(rtype, str(count))
        console.print(table)


def show_dry_run(workspace: Path, extensions: dict, unknown_policy: str, state: dict, force: bool) -> None:
    """Show what would be processed without actually doing it."""
    import os
    
    table = Table(title="Files to Process")
    table.add_column("Language", style="cyan")
    table.add_column("File", style="white")
    table.add_column("Status", style="green")

    files = _discover_files(workspace, extensions, unknown_policy)
    
    for file_path, language in files:
        source = str(file_path)
        current_hash = _file_hash(file_path)
        if force or state.get(source) != current_hash:
            status = "[yellow]will process[/yellow]"
        else:
            status = "[dim]unchanged (skip)[/dim]"
        lang_label = language or "topology_only"
        table.add_row(lang_label, file_path.name, status)

    console.print(table)

    to_process = sum(
        1 for fp, _ in files
        if force or state.get(str(fp)) != _file_hash(fp)
    )
    console.print(f"\n  Total: {len(files)} files, {to_process} to process")


def main():
    parser = argparse.ArgumentParser(
        description="Build knowledge graph from workspace (GraphRAG v2)",
    )
    parser.add_argument("--config", "-c", default="config.yaml", help="Config file path")
    parser.add_argument("--workspace", default=".", help="Workspace root directory")
    parser.add_argument("--force", "-f", action="store_true", help="Rebuild even if files unchanged")
    parser.add_argument("--clear", action="store_true", help="Clear graph and rebuild from scratch")
    parser.add_argument("--dry-run", "-n", action="store_true", help="Preview without processing")
    parser.add_argument("--stats", "-s", action="store_true", help="Show graph statistics and exit")
    parser.add_argument("--enrich", action="store_true", help="Run semantic enrichment only")
    parser.add_argument("--enrich-only", action="store_true", help="Run enrichment only (no structural changes)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    # Logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_path=False)],
    )
    for lib in ("httpx", "openai", "chromadb", "httpcore"):
        logging.getLogger(lib).setLevel(logging.WARNING)

    # Load config
    cfg = load_config(args.config)
    graph_cfg = cfg.get("graph", {})
    
    if not graph_cfg.get("enabled", True):
        console.print("[yellow]GraphRAG is disabled in config[/yellow]")
        return

    persist_dir = graph_cfg.get("db_path", ".graphdb/graph.sqlite")
    queries_dir = graph_cfg.get("queries_dir", "queries")
    
    # Validate queries directory exists
    queries_path = Path(queries_dir)
    if not queries_path.exists():
        console.print(f"[red]Queries directory not found: {queries_dir}[/red]")
        sys.exit(1)
    
    # Validate supported languages have corresponding .scm files
    supported = graph_cfg.get("supported_languages", [])
    for lang in supported:
        scm_file = queries_path / f"{lang}.scm"
        if not scm_file.exists():
            console.print(f"[red]Missing query file: {scm_file}[/red]")
            console.print("[dim]Add the .scm file or remove from supported_languages[/dim]")
            sys.exit(1)
    
    # Initialize graph store
    store = GraphStore(db_path=persist_dir)
    
    # Stats only mode
    if args.stats:
        show_stats(store)
        return
    
    # Validate API config for enrichment
    if not (args.enrich or args.enrich_only):
        if not graph_cfg.get("enabled", True):
            console.print("[red]GraphRAG is disabled[/red]")
            sys.exit(1)

    # Clear mode
    if args.clear:
        console.print("[yellow]Clearing existing graph...[/yellow]")
        store.clear()
        if STATE_FILE.exists():
            STATE_FILE.unlink()

    # Dry run
    if args.dry_run:
        workspace_path = Path(args.workspace).resolve()
        extensions = graph_cfg.get("extensions", {})
        unknown_policy = graph_cfg.get("unknown_language_policy", "topology_only")
        state = _load_state() if not args.clear else {}
        show_dry_run(workspace_path, extensions, unknown_policy, state, args.force)
        return

    # Build mode
    workspace_path = Path(args.workspace).resolve()
    if not workspace_path.exists():
        console.print(f"[red]Workspace not found: {workspace_path}[/red]")
        sys.exit(1)

    extensions = graph_cfg.get("extensions", {})
    unknown_policy = graph_cfg.get("unknown_language_policy", "topology_only")
    
    console.print(f"\n[bold]=== GraphRAG v2 Build ===[/bold]")
    console.print(f"  Workspace: {workspace_path}")
    console.print(f"  Graph DB: {persist_dir}")
    console.print(f"  Queries: {queries_dir}")
    console.print(f"  Force: {args.force}")
    console.print(f"  Enrich: {args.enrich or args.enrich_only}")

    state = _load_state() if not args.clear else {}

    # Phase 1: Topology layer (always runs)
    console.print("\n[bold]Phase 1/5: Topology[/bold]")
    start = time.time()
    _emit_topology_layers(store, workspace_path, cfg)
    topology_time = time.time() - start
    console.print(f"  [green]✓ Topology layer complete in {topology_time:.2f}s[/green]")

    # Phase 2: Structural extraction (only if not enrich-only)
    if not (args.enrich_only or args.enrich):
        console.print("\n[bold]Phase 2/5: Structural Extraction[/bold]")
        files = _discover_files(workspace_path, extensions, unknown_policy)
        
        structural_nodes = 0
        structural_edges = 0
        
        for file_path, language in files:
            source = str(file_path)
            current_hash = _file_hash(file_path)
            
            # Skip unchanged files unless forced
            if not args.force and state.get(source) == current_hash:
                continue
            
            if language:
                # Supported language with AST extraction
                try:
                    ncount, ecount = _process_file_with_structural_extraction(
                        store, file_path, language, queries_dir, cfg
                    )
                    structural_nodes += ncount
                    structural_edges += ecount
                    state[source] = current_hash
                except Exception as e:
                    logger.exception("Failed to process %s: %s", file_path, e)
            # else: topology_only file (File node already added in Phase 1)
        
        console.print(f"  [green]✓ Structural extraction: {structural_nodes} nodes, {structural_edges} edges[/green]")

    # Phase 3: Resolution (always runs after structural extraction)
    if not (args.enrich_only or args.enrich):
        console.print("\n[bold]Phase 3/5: Resolution[/bold]")
        start = time.time()
        resolution_stats = resolve_edges(store)
        resolution_time = time.time() - start
        console.print(f"  [green]✓ Resolution complete: {resolution_stats.resolved} resolved, {resolution_stats.unresolved} unresolved in {resolution_time:.2f}s[/green]")

    # Phase 4: Hub dampening (always runs)
    console.print("\n[bold]Phase 4/5: Hub Dampening[/bold]")
    start = time.time()
    dampened = apply_hub_node_dampening(store, cfg)
    dampen_time = time.time() - start
    console.print(f"  [green]✓ Hub dampening applied to {dampened} edges in {dampen_time:.2f}s[/green]")

    # Phase 5: Enrichment (optional, only if requested)
    if args.enrich or args.enrich_only:
        console.print("\n[bold]Phase 5/5: Semantic Enrichment[/bold]")
        start = time.time()
        
        # Load API client for enrichment
        defaults = cfg.get("_defaults", {})
        if not defaults.get("api_base_url") or not defaults.get("api_key"):
            console.print("[red]API_BASE_URL and API_KEY required for enrichment[/red]")
            sys.exit(1)
        
        model = get_model_for_agent(cfg, "graph")
        temperature = get_agent_temperature(cfg, "graph")
        if temperature == 0.5:
            temperature = graph_cfg.get("extraction_temperature", 0.1)
        
        client = ResilientClient(
            api_key=defaults["api_key"],
            base_url=defaults["api_base_url"],
            max_retries=defaults.get("retry_max_attempts", 8),
            base_delay=defaults.get("retry_base_delay", 2.0),
            max_delay=defaults.get("retry_max_delay", 120.0),
        )
        
        enrichment_stats = _run_enrichment_phase(store, client, cfg)
        enrich_time = time.time() - start
        console.print(f"  [green]✓ Enrichment complete: {enrichment_stats['enriched']} nodes enriched in {enrich_time:.2f}s[/green]")

    state = _load_state() if not args.clear else {}

    # Phase 1: Topology layer (always runs)
    console.print("\n[bold]Phase 1/5: Topology[/bold]")
    start = time.time()
    _emit_topology_layers(store, workspace_path, cfg)
    topology_time = time.time() - start
    console.print(f"  [green]✓ Topology layer complete in {topology_time:.2f}s[/green]")

    # Phase 2: Structural extraction (only if not enrich-only)
    if not (args.enrich_only or args.enrich):
        console.print("\n[bold]Phase 2/5: Structural Extraction[/bold]")
        files = _discover_files(workspace_path, extensions, unknown_policy)
        
        structural_nodes = 0
        structural_edges = 0
        
        for file_path, language in files:
            source = str(file_path)
            current_hash = _file_hash(file_path)
            
            # Skip unchanged files unless forced
            if not args.force and state.get(source) == current_hash:
                continue
            
            if language:
                # Supported language with AST extraction
                try:
                    ncount, ecount = _process_file_with_structural_extraction(
                        store, file_path, language, queries_dir, cfg
                    )
                    structural_nodes += ncount
                    structural_edges += ecount
                    state[source] = current_hash
                except Exception as e:
                    logger.exception("Failed to process %s: %s", file_path, e)
            # else: topology_only file (File node already added in Phase 1)
            
        console.print(f"  [green]✓ Structural extraction: {structural_nodes} nodes, {structural_edges} edges[/green]")

    # Phase 3: Resolution (always runs after structural extraction)
    if not (args.enrich_only or args.enrich):
        console.print("\n[bold]Phase 3/5: Resolution[/bold]")
        start = time.time()
        resolution_stats = resolve_edges(store)
        resolution_time = time.time() - start
        console.print(f"  [green]✓ Resolution complete: {resolution_stats.resolved} resolved, {resolution_stats.unresolved} unresolved in {resolution_time:.2f}s[/green]")

    # Phase 4: Hub dampening (always runs)
    console.print("\n[bold]Phase 4/5: Hub Dampening[/bold]")
    start = time.time()
    dampened = _apply_hub_dampening(store, cfg)
    dampen_time = time.time() - start
    console.print(f"  [green]✓ Hub dampening applied to {dampened} edges in {dampen_time:.2f}s[/green]")

    # Phase 5: Enrichment (optional, only if requested)
    if args.enrich or args.enrich_only:
        console.print("\n[bold]Phase 5/5: Semantic Enrichment[/bold]")
        start = time.time()
        
        # Load API client for enrichment
        defaults = cfg.get("_defaults", {})
        if not defaults.get("api_base_url") or not defaults.get("api_key"):
            console.print("[red]API_BASE_URL and API_KEY required for enrichment[/red]")
            sys.exit(1)
        
        model = get_model_for_agent(cfg, "graph")
        temperature = get_agent_temperature(cfg, "graph")
        if temperature == 0.5:
            temperature = graph_cfg.get("extraction_temperature", 0.1)
        
        client = ResilientClient(
            api_key=defaults["api_key"],
            base_url=defaults["api_base_url"],
            max_retries=defaults.get("retry_max_attempts", 8),
            base_delay=defaults.get("retry_base_delay", 2.0),
            max_delay=defaults.get("retry_max_delay", 120.0),
        )
        
        enrichment_stats = _run_enrichment_phase(store, client, cfg)
        enrich_time = time.time() - start
        console.print(f"  [green]✓ Enrichment complete: {enrichment_stats['enriched']} nodes enriched in {enrich_time:.2f}s[/green]")
    
    # Save state and stats
    _save_state(state)
    store.save()

    # Show final stats
    console.print(f"\n[bold green]=== Build Complete ===[/bold green]")
    show_stats(store)


if __name__ == "__main__":
    import os
    main()
