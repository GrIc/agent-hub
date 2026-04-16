#!/usr/bin/env python3
"""
build_graph.py -- Build the knowledge graph from documentation.

Reads codex docs and synthesis docs, extracts structured {subject, relation, object}
triplets via LLM, and stores them in a NetworkX graph persisted as JSON.

The graph complements the existing ChromaDB vector store by adding structural
context (dependencies, calls, inheritance) for hybrid GraphRAG queries.

Build order: L3 (codex per-file docs) first, then synthesis levels bottom-up
(L2+ -> L1 -> L0) so the graph captures both fine-grained and coarse-grained
relationships.

Duplicate node IDs are merged automatically.

Usage:
    python build_graph.py                      # Full build from all docs
    python build_graph.py --dry-run            # Preview docs to process
    python build_graph.py --stats              # Show graph statistics
    python build_graph.py --clear              # Clear and rebuild from scratch
    python build_graph.py --force              # Rebuild even if docs haven't changed
    python build_graph.py --source FILE        # Process a single document
"""

import argparse
import hashlib
import json
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
from src.rag.graph import KnowledgeGraph
from src.rag.graph_extract import TripletExtractor

console = Console()
logger = logging.getLogger(__name__)

DOCS_DIR = Path("context/docs")
SYNTH_DIR = DOCS_DIR / "synthesis"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _doc_level(path: Path) -> str:
    """Infer document level from filename.

    codex_*.md          -> L3 (per-file detail)
    L0_*.md             -> L0
    L1_*.md             -> L1
    L2_*.md, L5_*.md    -> L2, L5, etc.
    """
    name = path.stem
    if name.startswith("codex_"):
        return "L3"
    for i in range(20):
        if name.startswith(f"L{i}_"):
            return f"L{i}"
    return "unknown"


def _file_hash(path: Path) -> str:
    """Quick content hash for change detection."""
    try:
        return hashlib.md5(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _discover_docs() -> list[tuple[Path, str]]:
    """Discover all processable documents.

    Returns list of (path, doc_level) sorted by level descending (L3 first,
    then highest LN, down to L0) so fine-grained docs are processed before
    coarse overviews.
    """
    docs = []

    # Codex docs (L3)
    for p in sorted(DOCS_DIR.glob("codex_*.md")):
        docs.append((p, "L3"))

    # Synthesis docs (L0, L1, L2+)
    if SYNTH_DIR.exists():
        for p in sorted(SYNTH_DIR.glob("L*_*.md")):
            level = _doc_level(p)
            if level != "unknown":
                docs.append((p, level))

    # Sort: highest level number first (L3 -> L2 -> L1 -> L0)
    def level_key(item):
        level = item[1]
        try:
            return -int(level[1:])
        except (ValueError, IndexError):
            return 0

    docs.sort(key=level_key)
    return docs


# ---------------------------------------------------------------------------
# State tracking (avoid re-processing unchanged docs)
# ---------------------------------------------------------------------------

STATE_FILE = Path(".graphdb") / "build_state.json"


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Validation and Graph Processing
# ---------------------------------------------------------------------------

def validate_triplets(
    nodes: list[dict],
    edges: list[dict],
    config: dict,
) -> tuple[list[dict], list[dict]]:
    """Post-extraction validation: filter invalid nodes and edges.

    Args:
        nodes: List of node dictionaries with 'id', 'label', 'type' keys
        edges: List of edge dictionaries with 'source', 'target', 'relation' keys
        config: Application config containing knowledge_graph schema

    Returns:
        (clean_nodes, clean_edges) with invalid items removed
    """
    knowledge_graph_cfg = config.get("knowledge_graph", {})
    valid_types = set(knowledge_graph_cfg.get("node_types", []))
    valid_rels = set(knowledge_graph_cfg.get("relation_types", []))
    allowed_relations = knowledge_graph_cfg.get("allowed_relations", {})

    # Filter nodes by type
    clean_nodes = [
        n for n in nodes 
        if n.get("id") and n.get("label") and n.get("type") in valid_types
    ]

    # Build set of valid node IDs
    node_ids = {n["id"] for n in clean_nodes}

    # Filter edges by relation type and node existence
    clean_edges = []
    for e in edges:
        if not e.get("source") or not e.get("target") or not e.get("relation"):
            continue
        
        # Check if relation is valid for source node type
        source_type = None
        for node in clean_nodes:
            if node["id"] == e["source"]:
                source_type = node.get("type")
                break
        
        rel = e["relation"]
        if source_type and rel not in allowed_relations.get(source_type, []):
            logger.debug(
                f"Rejected edge {e['source']} --[{rel}]--> {e['target']}: "
                f"relation not allowed for node type '{source_type}'"
            )
            continue
        
        if rel not in valid_rels:
            logger.debug(
                f"Rejected edge {e['source']} --[{rel}]--> {e['target']}: "
                f"relation type '{rel}' not in valid types"
            )
            continue
        
        if e["source"] not in node_ids or e["target"] not in node_ids:
            logger.debug(
                f"Rejected edge {e['source']} --[{rel}]--> {e['target']}: "
                f"source or target node does not exist"
            )
            continue
        
        clean_edges.append(e)

    logger.info(
        f"[Validation] Kept {len(clean_nodes)} nodes, {len(clean_edges)} edges "
        f"(filtered from {len(nodes)} nodes, {len(edges)} edges)"
    )
    return clean_nodes, clean_edges


def apply_hub_node_dampening(graph: KnowledgeGraph, dampening_factor: float = 0.3) -> int:
    """Apply dampening to edges of hub nodes (nodes connected to >20% of other nodes).

    Args:
        graph: KnowledgeGraph instance
        dampening_factor: Multiplier to apply to hub node edges (default: 0.3)

    Returns:
        Number of edges modified
    """
    if not graph.G.nodes:
        return 0

    total_nodes = len(graph.G.nodes)
    threshold = 0.2 * total_nodes  # >20% of nodes

    modified_edges = 0
    
    for node_id in graph.G.nodes:
        # Count outgoing edges (degree)
        out_degree = graph.G.out_degree(node_id)
        if out_degree > threshold:
            logger.info(
                f"[HubDampening] Node '{node_id}' is a hub ({out_degree} edges, "
                f"threshold: {threshold:.0f})"
            )
            
            # Apply dampening to all outgoing edges
            for target_id in graph.G.successors(node_id):
                if graph.G.has_edge(node_id, target_id):
                    weight = graph.G.edges[node_id, target_id].get("weight", 1.0)
                    dampened_weight = weight * dampening_factor
                    graph.G.edges[node_id, target_id]["weight"] = dampened_weight
                    modified_edges += 1
                    logger.debug(
                        f"  Dampened edge {node_id} -> {target_id}: "
                        f"{weight:.2f} -> {dampened_weight:.2f}"
                    )

    logger.info(f"[HubDampening] Modified {modified_edges} edges")
    return modified_edges


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

class GraphBuilder:
    """Orchestrates knowledge graph construction from documentation."""

    def __init__(
        self,
        client: ResilientClient,
        model: str,
        temperature: float = 0.1,
        graph: KnowledgeGraph | None = None,
        force: bool = False,
        config: Optional[dict] = None,
    ):
        self.client = client
        self.model = model
        self.force = force
        self.graph = graph or KnowledgeGraph()
        self.extractor = TripletExtractor(
            client=client,
            model=model,
            temperature=temperature,
        )
        self.stats = {
            "processed": 0,
            "skipped": 0,
            "failed": 0,
            "total_nodes": 0,
            "total_edges": 0,
            "llm_calls": 0,
        }
        # Configure extractor with schema from config
        if config is not None:
            self._configure_extractor_from_config(config)

    def _configure_extractor_from_config(self, config: dict) -> None:
        """Configure the extractor with schema from config.

        Args:
            config: Application config containing knowledge_graph schema
        """
        knowledge_graph_cfg = config.get("knowledge_graph", {})
        
        # Update entity and relation types
        if knowledge_graph_cfg.get("node_types"):
            self.extractor.entity_types = knowledge_graph_cfg["node_types"]
        
        if knowledge_graph_cfg.get("relation_types"):
            self.extractor.relation_types = knowledge_graph_cfg["relation_types"]
        
        # Set allowed relations for prompt formatting
        if knowledge_graph_cfg.get("allowed_relations"):
            self.extractor.allowed_relations = knowledge_graph_cfg["allowed_relations"]

    def process_doc(
        self,
        doc_path: Path,
        doc_level: str,
        state: dict,
        config: dict,
    ) -> bool:
        """Extract triplets from a single doc, validate, and add to graph.

        Returns True if the doc was processed, False if skipped.
        """
        source = str(doc_path)
        current_hash = _file_hash(doc_path)

        # Skip unchanged docs unless forced
        if not self.force and state.get(source) == current_hash:
            self.stats["skipped"] += 1
            return False

        try:
            text = doc_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            logger.warning(f"Cannot read {doc_path}: {e}")
            self.stats["failed"] += 1
            return False

        if len(text.strip()) < 50:
            logger.debug(f"Skipping {doc_path.name}: too short")
            self.stats["skipped"] += 1
            state[source] = current_hash
            return False

        console.print(f"  Processing [cyan]{doc_path.name}[/cyan] ({doc_level})...", end=" ")

        # Remove old data for this source before re-extracting
        removed = self.graph.remove_nodes_by_source(source)
        if removed:
            logger.debug(f"Removed {removed} stale nodes from {source}")

        # Extract triplets
        nodes, edges = self.extractor.extract_from_doc(
            doc_text=text,
            doc_source=source,
            doc_level=doc_level,
        )
        self.stats["llm_calls"] += 1

        if not nodes and not edges:
            console.print("[yellow]no triplets extracted[/yellow]")
            self.stats["failed"] += 1
            return False

        # Validate extracted triplets against schema
        nodes, edges = validate_triplets(nodes, edges, config)

        if not nodes and not edges:
            console.print("[yellow]no valid triplets after validation[/yellow]")
            self.stats["failed"] += 1
            return False

        # Add to graph
        for node in nodes:
            self.graph.add_node(
                id=node["id"],
                label=node["label"],
                type=node["type"],
                source_doc=node.get("source_doc", source),
                doc_level=node.get("doc_level", doc_level),
            )

        for edge in edges:
            self.graph.add_edge(
                source=edge["source"],
                target=edge["target"],
                relation=edge["relation"],
                weight=edge.get("weight", 0.7),
                source_doc=edge.get("source_doc", source),
                doc_level=edge.get("doc_level", doc_level),
            )

        self.stats["processed"] += 1
        self.stats["total_nodes"] += len(nodes)
        self.stats["total_edges"] += len(edges)
        console.print(f"[green]{len(nodes)} nodes, {len(edges)} edges[/green]")

        # Update state
        state[source] = current_hash

        # Rate limit: avoid hammering the LLM API
        time.sleep(1)
        return True

    def build_all(self, docs: list[tuple[Path, str]], state: dict, config: dict) -> None:
        """Process all documents."""
        if not docs:
            console.print("[yellow]No documents found to process.[/yellow]")
            return

        # Group by level for display
        by_level: dict[str, list] = {}
        for path, level in docs:
            by_level.setdefault(level, []).append(path)

        for level in sorted(by_level, key=lambda l: -int(l[1:]) if l[1:].isdigit() else 0):
            paths = by_level[level]
            console.print(f"\n[bold]{level}[/bold] — {len(paths)} document(s)")
            for path in paths:
                self.process_doc(path, level, state, config)


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def show_stats(graph: KnowledgeGraph) -> None:
    """Display graph statistics with Rich tables."""
    stats = graph.stats()

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


def show_dry_run(docs: list[tuple[Path, str]], state: dict, force: bool) -> None:
    """Show what would be processed without actually doing it."""
    table = Table(title="Documents to Process")
    table.add_column("Level", style="cyan")
    table.add_column("Document", style="white")
    table.add_column("Status", style="green")

    for path, level in docs:
        source = str(path)
        current_hash = _file_hash(path)
        if force or state.get(source) != current_hash:
            status = "[yellow]will process[/yellow]"
        else:
            status = "[dim]unchanged (skip)[/dim]"
        table.add_row(level, path.name, status)

    console.print(table)

    to_process = sum(
        1 for p, l in docs
        if force or state.get(str(p)) != _file_hash(p)
    )
    console.print(f"\n  Total: {len(docs)} docs, {to_process} to process")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Build knowledge graph from documentation",
    )
    parser.add_argument("--config", "-c", default="config.yaml", help="Config file path")
    parser.add_argument("--source", help="Process a single document file")
    parser.add_argument("--force", "-f", action="store_true", help="Rebuild even if docs haven't changed")
    parser.add_argument("--clear", action="store_true", help="Clear graph and rebuild from scratch")
    parser.add_argument("--dry-run", "-n", action="store_true", help="Preview without processing")
    parser.add_argument("--stats", "-s", action="store_true", help="Show graph statistics and exit")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    # -- Logging ---------------------------------------------------------------
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_path=False)],
    )
    for lib in ("httpx", "openai", "chromadb", "httpcore"):
        logging.getLogger(lib).setLevel(logging.WARNING)

    # -- Config ----------------------------------------------------------------
    cfg = load_config(args.config)
    defaults = cfg.get("_defaults", {})
    graph_cfg = cfg.get("graph", {})

    persist_dir = graph_cfg.get("persist_dir", ".graphdb")
    graph = KnowledgeGraph(persist_dir=persist_dir)

    # -- Stats only ------------------------------------------------------------
    if args.stats:
        show_stats(graph)
        return

    # -- Validate API config ---------------------------------------------------
    if not args.dry_run:
        if not defaults.get("api_base_url") or not defaults.get("api_key"):
            console.print("[red]API_BASE_URL and API_KEY required in .env[/red]")
            sys.exit(1)

    # -- Clear -----------------------------------------------------------------
    if args.clear:
        console.print("[yellow]Clearing existing graph...[/yellow]")
        graph.clear()
        graph.save()
        # Also clear build state
        if STATE_FILE.exists():
            STATE_FILE.unlink()

    # -- Discover docs ---------------------------------------------------------
    if args.source:
        source_path = Path(args.source)
        if not source_path.exists():
            console.print(f"[red]File not found: {args.source}[/red]")
            sys.exit(1)
        docs = [(source_path, _doc_level(source_path))]
    else:
        docs = _discover_docs()

    if not docs:
        console.print("[yellow]No documents found in context/docs/[/yellow]")
        console.print("Run the codex agent or synthesize.py first to generate documentation.")
        return

    state = _load_state() if not args.clear else {}

    # -- Dry run ---------------------------------------------------------------
    if args.dry_run:
        show_dry_run(docs, state, args.force)
        return

    # -- Build -----------------------------------------------------------------
    console.print(f"\n[bold]=== Building Knowledge Graph ===[/bold]")
    console.print(f"  Documents: {len(docs)}")
    console.print(f"  Graph dir: {persist_dir}/")
    console.print(f"  Force: {args.force}")

    # Resolve model from config (uses graph agent config, fallback to codex)
    model = get_model_for_agent(cfg, "graph")
    if model == "heavy":
        model = get_model_for_agent(cfg, "codex")
    temperature = get_agent_temperature(cfg, "graph")
    if temperature == 0.5:  # default = not configured
        temperature = graph_cfg.get("extraction_temperature", 0.1)

    client = ResilientClient(
        api_key=defaults["api_key"],
        base_url=defaults["api_base_url"],
        max_retries=defaults.get("retry_max_attempts", 8),
        base_delay=defaults.get("retry_base_delay", 2.0),
        max_delay=defaults.get("retry_max_delay", 120.0),
    )

    builder = GraphBuilder(
        client=client,
        model=model,
        temperature=temperature,
        graph=graph,
        force=args.force,
        config=cfg,
    )

    builder.build_all(docs, state, cfg)

    # Apply hub node dampening
    dampened_count = apply_hub_node_dampening(graph)

    # -- Save ------------------------------------------------------------------
    graph.save()
    _save_state(state)

    # -- Summary ----------------------------------------------------------------
    console.print(f"\n[bold green]=== Build Complete ===[/bold green]")
    console.print(f"  Processed : {builder.stats['processed']}")
    console.print(f"  Skipped   : {builder.stats['skipped']}")
    console.print(f"  Failed    : {builder.stats['failed']}")
    console.print(f"  LLM calls : {builder.stats['llm_calls']}")
    console.print(f"  New nodes : {builder.stats['total_nodes']}")
    console.print(f"  New edges : {builder.stats['total_edges']}")
    if dampened_count > 0:
        console.print(f"  Hub dampened edges: {dampened_count}")

    show_stats(graph)


if __name__ == "__main__":
    main()
