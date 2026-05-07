"""Language-agnostic LLM enrichment for GraphRAG (Phase 2).

Enriches Class and Service nodes with grounded descriptions and intent classifications.
Uses Phase 1 grounding via prepend_grounding().

This module is intentionally language-agnostic: it consumes AST-extracted node
neighborhoods (callers, callees, methods, annotations) rather than source language.
"""

import json
import logging
from typing import Optional, Set, Dict, Any, Tuple

from src.rag.grounding import prepend_grounding, ABSTAIN_TOKEN

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Intent taxonomy (configurable via ALLOWED_INTENTS)
# ---------------------------------------------------------------------------

ALLOWED_INTENTS: Set[str] = frozenset({
    "data",
    "logic",
    "io",
    "controller",
    "service",
    "repository",
    "utility",
    "config",
    "test",
    "entrypoint",
    "unknown",
})

# ---------------------------------------------------------------------------
# Prompt templates (language-agnostic)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a senior software architect reviewing code structure.

TASK:
- Write a concise 1-2 sentence description of the node's purpose.
- Classify its INTENT into one of: {allowed_intents}
- Keep the description grounded ONLY in the provided neighborhood.
- If unclear, return the abstain token: {abstain_token}

RULES:
- Do NOT invent names or behaviors not present in the neighborhood.
- Do NOT mention the programming language.
- Do NOT use generic framework terms unless they appear in the neighborhood.
- Be specific and technical.
"""

USER_TEMPLATE = """Node to enrich:
- id: {node_id}
- type: {node_type}
- name: {node_name}
- file: {file_path}

Neighborhood evidence:
{neighborhood_text}

Respond with a JSON object containing:
- description: str (≤200 chars, grounded)
- intent: str (one of {allowed_intents})
- confidence: float (0.0–1.0; 0.0 if abstain)

Example response:
{example_response}
"""

EXAMPLE_RESPONSE = json.dumps({
    "description": "Coordinates user authentication and session management.",
    "intent": "controller",
    "confidence": 0.95
}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Core enrichment functions
# ---------------------------------------------------------------------------


def build_neighborhood_text(store, node_id: str) -> str:
    """Build a language-agnostic neighborhood description for any node.
    
    Returns a multi-line string suitable for LLM prompts.
    """
    node = store.get_node(node_id)
    if not node:
        return "Node not found in store."
    
    # Get neighbors
    neighbors = store.get_neighbors(node_id)
    
    lines = []
    lines.append(f"Node: {node['name']} ({node['type']})")
    lines.append(f"File: {node.get('file_path', 'unknown')}")
    lines.append("")
    
    # Callers
    if neighbors.get('incoming'):
        lines.append("Callers:")
        for inc in neighbors['incoming']:
            caller_name = inc.get('source_name', '?')
            caller_type = inc.get('source_type', '?')
            lines.append(f"  - {caller_name} ({caller_type})")
    
    # Callees
    if neighbors.get('outgoing'):
        lines.append("Callees:")
        for out in neighbors['outgoing']:
            callee_name = out.get('target_name', '?')
            callee_type = out.get('target_type', '?')
            lines.append(f"  - {callee_name} ({callee_type})")
    
    # Annotations/metadata if present
    metadata = node.get('metadata', {})
    if metadata:
        lines.append("Metadata:")
        for k, v in metadata.items():
            lines.append(f"  - {k}: {v}")
    
    return "\n".join(lines)


def enrich_node(
    store,
    node_id: str,
    llm_client: Any,
    source_text: str,
    *,
    allowed_intents: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Enrich a single node with description and intent via LLM.
    
    Args:
        store: GraphStore instance
        node_id: Node identifier
        llm_client: LLM client with a chat/completion interface
        source_text: Original source text (for hashing and grounding)
        allowed_intents: Optional override for intent taxonomy
    
    Returns:
        Dict with keys: description, intent, confidence
        If unclear or error: abstain with confidence=0.0
    """
    allowed = allowed_intents or ALLOWED_INTENTS
    
    # Fetch node
    node = store.get_node(node_id)
    if not node:
        logger.warning("Node %s not found; abstaining", node_id)
        return {
            "description": ABSTAIN_TOKEN,
            "intent": "unknown",
            "confidence": 0.0,
        }
    
    # Skip if not Class or Service by default (config-tunable via only_types)
    if node.get('type') not in ("Class", "Service"):
        logger.debug("Skipping enrichment for non-Class/Service node: %s (%s)", 
                    node_id, node.get('type'))
        return {
            "description": "",
            "intent": "",
            "confidence": 0.0,
        }
    
    # Build neighborhood text
    neighborhood_text = build_neighborhood_text(store, node_id)
    
    # Prepare prompt
    user_prompt = USER_TEMPLATE.format(
        node_id=node_id,
        node_type=node['type'],
        node_name=node['name'],
        file_path=node.get('file_path', 'unknown'),
        neighborhood_text=neighborhood_text,
        allowed_intents=", ".join(sorted(allowed)),
        abstain_token=ABSTAIN_TOKEN,
        example_response=EXAMPLE_RESPONSE,
    )
    
    system_prompt = SYSTEM_PROMPT.format(
        allowed_intents=", ".join(sorted(allowed)),
        abstain_token=ABSTAIN_TOKEN,
    )
    system_prompt = prepend_grounding(system_prompt)
    
    try:
        # Call LLM
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        
        response = llm_client.chat.completions.create(
            model="",  # Use default or configured model
            messages=messages,
            temperature=0.3,
            max_tokens=300,
            top_p=1.0,
        )
        
        content = response.choices[0].message.content
        
        # Parse JSON
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning("LLM returned invalid JSON for %s: %s", node_id, e)
            return {
                "description": ABSTAIN_TOKEN,
                "intent": "unknown",
                "confidence": 0.0,
            }
        
        # Validate fields
        description = parsed.get('description', ABSTAIN_TOKEN)
        intent = parsed.get('intent', 'unknown')
        confidence = parsed.get('confidence', 0.0)
        
        # Cap description length
        if isinstance(description, str) and len(description) > 200:
            description = description[:197] + "..."
        
        # Validate intent
        if intent not in allowed:
            logger.warning("Invalid intent '%s' for node %s; defaulting to unknown", 
                        intent, node_id)
            intent = "unknown"
        
        # Clamp confidence
        confidence = max(0.0, min(1.0, float(confidence)))
        
        result = {
            "description": description,
            "intent": intent,
            "confidence": confidence,
        }
        
        logger.info("Enriched node %s: intent=%s confidence=%.2f", 
                   node_id, intent, confidence)
        return result
        
    except Exception as e:
        logger.exception("Failed to enrich node %s: %s", node_id, e)
        return {
            "description": ABSTAIN_TOKEN,
            "intent": "unknown",
            "confidence": 0.0,
        }


def enrich_all(
    store,
    llm_client: Any,
    *,
    only_types: Optional[Set[str]] = None,
    allowed_intents: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Enrich all eligible nodes in the graph.
    
    Args:
        store: GraphStore instance
        llm_client: LLM client
        only_types: Optional set of node types to enrich (default: {"Class", "Service"})
        allowed_intents: Optional intent taxonomy override
    
    Returns:
        Dict with enrichment statistics:
        - total: int
        - enriched: int
        - skipped: int
        - errors: int
        - by_intent: Dict[str, int]
    """
    allowed_types = only_types or {"Class", "Service"}
    allowed_intents_set = allowed_intents or ALLOWED_INTENTS
    
    stats = {
        "total": 0,
        "enriched": 0,
        "skipped": 0,
        "errors": 0,
        "by_intent": {intent: 0 for intent in allowed_intents_set},
    }
    
    # List all nodes of allowed types
    nodes = store.list_nodes(node_type=None, limit=100000)
    eligible = [n for n in nodes if n['type'] in allowed_types]
    stats["total"] = len(eligible)
    
    logger.info("Enriching %d eligible nodes", len(eligible))
    
    for node in eligible:
        node_id = node['id']
        metadata = node.get('metadata', {})
        source_hash = metadata.get('source_hash')
        
        # Incremental skipping: if source_hash unchanged, skip
        if source_hash and metadata.get('enrichment_version') == "2.0":
            # Already enriched in this version; skip
            stats["skipped"] += 1
            continue
        
        # Enrich
        result = enrich_node(
            store,
            node_id,
            llm_client,
            source_text="",  # Not used in v2; kept for API compatibility
            allowed_intents=allowed_intents_set,
        )
        
        description = result.get('description', '')
        intent = result.get('intent', 'unknown')
        confidence = result.get('confidence', 0.0)
        
        # Update node metadata
        new_metadata = metadata.copy()
        new_metadata.update({
            "enrichment_version": "2.0",
            "description": description,
            "intent": intent,
            "enrichment_confidence": confidence,
        })
        
        store.upsert_node(
            id=node_id,
            type=node['type'],
            name=node['name'],
            file_path=node.get('file_path'),
            line_start=node.get('line_start'),
            line_end=node.get('line_end'),
            metadata=new_metadata,
        )
        
        if description == ABSTAIN_TOKEN or confidence <= 0.0:
            stats["errors"] += 1
        else:
            stats["enriched"] += 1
            stats["by_intent"][intent] += 1
    
    logger.info("Enrichment complete: %s", stats)
    return stats
