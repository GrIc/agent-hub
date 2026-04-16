"""
Triplet extraction from documentation via LLM.

Reads codex/synthesis docs and extracts structured {subject, relation, object}
triplets for the knowledge graph. Uses constrained JSON output with strict
anti-hallucination rules.
"""

import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

EXTRACTION_SYSTEM_PROMPT = """\
You are a knowledge graph extraction engine. Extract structured relationships
from the technical documentation below.

Output ONLY a valid JSON object with two arrays — no markdown, no explanation:
{{
  "nodes": [
    {{"id": "<type>:<normalized_name>", "label": "<DisplayName>", "type": "<EntityType>"}}
  ],
  "edges": [
    {{"source": "<node_id>", "target": "<node_id>", "relation": "<RelationType>", "weight": 0.9}}
  ]
}}

Entity types (use ONLY these): {entity_types}

Relation types (use ONLY these): {relation_types}

Allowed relations by entity type:
{allowed_relations_schema}

Rules:
- Extract ONLY relationships explicitly stated or directly visible in the text.
  Do NOT infer, guess, or extrapolate relationships.
- Normalize node IDs: lowercase, replace spaces with underscores, prefix with type.
  Examples: "class:user_service", "module:auth", "file:app_py"
- Weight reflects confidence: 1.0 = explicitly stated, 0.7 = strongly implied, 0.5 = loosely mentioned.
- If the document is a high-level overview (architecture, layer), extract coarse-grained
  relationships: Layer contains Module, Module depends_on Module, Service uses Database.
- If the document is detailed (per-file, per-class), extract fine-grained relationships:
  Class calls Function, Class implements Interface, File imports File.
- Skip trivial relationships (e.g., a class containing its own constructor).
- Produce 5-40 nodes and 10-60 edges for a typical document. Less for short docs.
- NEVER invent nodes or relations not present in the text.
"""

RETRY_NUDGE = (
    "Your previous response was not valid JSON. "
    "Please output ONLY a JSON object with 'nodes' and 'edges' arrays. "
    "No markdown fences, no explanation."
)


class TripletExtractor:
    """Extracts knowledge graph triplets from documentation using an LLM."""

    def __init__(
        self,
        client,
        model: str,
        temperature: float = 0.1,
        entity_types: Optional[list[str]] = None,
        relation_types: Optional[list[str]] = None,
    ):
        self.client = client
        self.model = model
        self.temperature = temperature
        # Default types - will be overridden by config if provided
        self.entity_types = entity_types or [
            "Module", "Class", "Interface", "Function", "File", "Package",
            "Layer", "Service", "API", "Database", "Config", "Library", "Pattern",
        ]
        self.relation_types = relation_types or [
            "imports", "calls", "depends_on", "contains", "implements", "extends",
            "uses", "exposes", "configures", "reads_from", "writes_to",
            "inherits", "instantiates", "tested_by",
        ]
        # Store allowed relations for validation
        self.allowed_relations: dict[str, list[str]] = {}

    def extract_from_doc(
        self,
        doc_text: str,
        doc_source: str,
        doc_level: str,
    ) -> tuple[list[dict], list[dict]]:
        """Extract triplets from a single document.

        Returns:
            (nodes, edges) where each is a list of dicts ready for KnowledgeGraph.
        """
        if not doc_text.strip() or len(doc_text) < 50:
            return [], []

        # Truncate very long docs
        text = doc_text[:30_000]

        # Format allowed relations for prompt
        allowed_relations_schema = ""
        if self.allowed_relations:
            lines = []
            for node_type, rels in self.allowed_relations.items():
                lines.append(f"  {node_type}: {', '.join(rels)}")
            allowed_relations_schema = "\n".join(lines)
        else:
            allowed_relations_schema = "  (No restrictions - use any valid relation)"

        system = EXTRACTION_SYSTEM_PROMPT.format(
            entity_types=", ".join(self.entity_types),
            relation_types=", ".join(self.relation_types),
            allowed_relations_schema=allowed_relations_schema,
        )

        raw = self._call_llm(system, text)
        parsed = self._parse_response(raw)

        if parsed is None:
            # Retry once with nudge
            raw = self._call_llm(system, text + "\n\n" + RETRY_NUDGE)
            parsed = self._parse_response(raw)

        if parsed is None:
            logger.warning(f"[GraphExtract] Failed to extract from {doc_source}")
            return [], []

        # Enrich with source metadata
        nodes = []
        for n in parsed.get("nodes", []):
            if not n.get("id") or not n.get("label") or not n.get("type"):
                continue
            nodes.append({
                "id": self._normalize_id(n["id"]),
                "label": n["label"],
                "type": n["type"] if n["type"] in self.entity_types else "Module",
                "source_doc": doc_source,
                "doc_level": doc_level,
            })

        edges = []
        for e in parsed.get("edges", []):
            if not e.get("source") or not e.get("target") or not e.get("relation"):
                continue
            edges.append({
                "source": self._normalize_id(e["source"]),
                "target": self._normalize_id(e["target"]),
                "relation": e["relation"] if e["relation"] in self.relation_types else "uses",
                "weight": min(1.0, max(0.0, float(e.get("weight", 0.7)))),
                "source_doc": doc_source,
                "doc_level": doc_level,
            })

        logger.info(
            f"[GraphExtract] {doc_source}: {len(nodes)} nodes, {len(edges)} edges"
        )
        return nodes, edges

    def _call_llm(self, system: str, content: str) -> str:
        """Call the LLM for extraction."""
        try:
            return self.client.chat(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": content},
                ],
                model=self.model,
                temperature=self.temperature,
                max_tokens=4096,
            )
        except Exception as e:
            logger.error(f"[GraphExtract] LLM call failed: {e}")
            return ""

    def _parse_response(self, raw: str) -> Optional[dict]:
        """Parse LLM response as JSON. Handles markdown fences and partial JSON."""
        if not raw:
            return None

        # Strip markdown fences if present
        cleaned = raw.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

        # Try to find JSON object
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if not match:
            return None

        try:
            data = json.loads(match.group())
        except json.JSONDecodeError:
            return None

        if not isinstance(data, dict):
            return None
        if "nodes" not in data or "edges" not in data:
            return None
        if not isinstance(data["nodes"], list) or not isinstance(data["edges"], list):
            return None

        return data

    @staticmethod
    def _normalize_id(raw_id: str) -> str:
        """Normalize a node ID: lowercase, no spaces, keep type prefix."""
        normalized = raw_id.strip().lower()
        normalized = re.sub(r"\s+", "_", normalized)
        # Ensure type:name format
        if ":" not in normalized:
            normalized = f"module:{normalized}"
        return normalized
