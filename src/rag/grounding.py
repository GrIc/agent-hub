"""Shared grounding utilities for all LLM calls in Agent Hub.

Every LLM call in the indexing pipeline (codex, synthesis) and at serve time
(MCP tools that produce prose) MUST go through one of:
- prepend_grounding(system_prompt) for prompt augmentation
- contains_abstain(text) to detect honest abstain
- ABSTAIN_TOKEN as the canonical abstain marker

Do NOT modify GROUNDING_INSTRUCTION without versioning it (G_VERSION).
"""

G_VERSION = "1.0.0"

ABSTAIN_TOKEN = "[INSUFFICIENT_EVIDENCE]"

GROUNDING_INSTRUCTION = """
ABSOLUTE RULES — VIOLATION = REJECT:

1. Mention ONLY names (classes, methods, fields, files, modules) that appear verbatim in the inputs below.
2. If a name does not appear in the inputs, DO NOT mention it. Do NOT invent. Do NOT guess.
3. For every claim about behavior, the supporting code MUST be quotable from the inputs.
4. If you cannot ground a claim, write the literal token [INSUFFICIENT_EVIDENCE] and continue.
   Do NOT fill gaps with plausible-sounding text.
5. When in doubt about whether something exists, omit it.
6. Do NOT use generic framework terms (Spring, JPA, Repository, etc.) as if they were specific
   project entities unless they appear in the inputs as such.

REJECTION POLICY: any output containing names not present in the inputs (other than the
allowed noise-filter terms) will be rejected and you will be asked to retry. Three
rejections will cause this section to be marked as [INSUFFICIENT_EVIDENCE] permanently.
""".strip()


def prepend_grounding(system_prompt: str) -> str:
    """Return system_prompt with GROUNDING_INSTRUCTION prepended.

    Always use this when constructing the system message for an LLM call
    in the indexing pipeline.
    """
    return f"{GROUNDING_INSTRUCTION}\n\n---\n\n{system_prompt}"


def contains_abstain(text: str) -> bool:
    """True if the text contains the canonical abstain token."""
    return ABSTAIN_TOKEN in text


def strip_abstain_blocks(text: str) -> str:
    """Remove [INSUFFICIENT_EVIDENCE] markers cleanly from prose for display.

    Useful at serve time when we want to surface a doc to a human but not
    flood it with abstain markers. The MCP tool layer does NOT use this —
    it preserves the markers as a quality signal.
    """
    # Replace lines containing only the token
    lines = []
    for line in text.split('\n'):
        if line.strip() == ABSTAIN_TOKEN:
            continue
        lines.append(line)
    cleaned = '\n'.join(lines)
    
    # Replace inline tokens with "(unknown)"
    cleaned = cleaned.replace(ABSTAIN_TOKEN, "(unknown)")
    
    return cleaned


# === noise filter ===

# Loaded from config.yaml at import time; see load_noise_filter().
DEFAULT_NOISE_FILTER: frozenset[str] = frozenset({
    # generic framework terms — extend in config.yaml: noise_filter.terms
    "Spring", "JPA", "Hibernate", "Repository", "Controller", "Service",
    "Entity", "Component", "Autowired", "Bean", "REST", "HTTP", "JSON",
    "XML", "SQL", "CRUD", "API", "DTO", "DAO", "POJO", "ORM",
    # ... (see config.yaml for the full list, this is a fallback only)
})

# Backwards compatibility
GROUNDING_VERSION = G_VERSION
NOISE_FILTER_TERMS = DEFAULT_NOISE_FILTER


def load_noise_filter(config: dict) -> frozenset[str]:
    """Build the noise filter from DEFAULT_NOISE_FILTER + config + auto-derived terms.

    config["noise_filter"]["terms"] is a user-extensible list.
    config["noise_filter"]["language_presets"] is a list like ["java-spring", "python-django"].
    Auto-derived: top-N most common imports across the workspace (computed elsewhere).
    """
    # Start with DEFAULT_NOISE_FILTER
    terms = set(DEFAULT_NOISE_FILTER)
    
    # Add user-extensible terms from config
    if config and "noise_filter" in config and "terms" in config["noise_filter"]:
        terms.update(config["noise_filter"]["terms"])
    
    # Convert to frozenset for immutability and hashability
    return frozenset(terms)
