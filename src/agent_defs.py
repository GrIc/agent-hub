"""
Load agent definitions from Markdown files.
Extract the system prompt, linked agents (peers), and config metadata.

Config is declared in an optional ## Config section in the .md file:
    ## Config
    - scope: global | project
    - web: yes | no
    - emoji: 🔍
    - description: Short description of what this agent does
    - model: heavy | code | light | reasoning (alias from config.yaml)
    - temperature: 0.3
    - doc_type: analysis (for project agents)
    - output_tag: analysis_md (for project agents)
    - upstream_types: requirements, specifications (for project agents)
"""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

DEFS_DIR = Path("agents/defs")

# Agents with dedicated Python classes (special commands like /scan, /apply, etc.)
CORE_AGENTS = {
    "expert", "codex", "documenter", "developer",
    "portfolio", "specifier", "planner", "architect", "presenter",
}


def load_agent_definition(agent_name: str) -> dict:
    """
    Load an agent's markdown definition file.

    Returns:
        {
            "system_prompt": str,
            "peers": list[str],
            "config": dict,    # Parsed from ## Config section
            "raw": str,
        }
    """
    md_path = DEFS_DIR / f"{agent_name}.md"

    if not md_path.exists():
        logger.warning(f"No definition file found for agent '{agent_name}' at {md_path}")
        return {
            "system_prompt": f"You are an expert technical assistant named '{agent_name}'. Respond in English.",
            "peers": [],
            "config": {},
            "raw": "",
        }

    raw = md_path.read_text(encoding="utf-8")

    peers = _extract_peers(raw)
    config = _extract_config(raw)
    system_prompt = _clean_for_prompt(raw)

    logger.info(f"Loaded definition for '{agent_name}': {len(system_prompt)} chars, peers={peers}, config keys={list(config.keys())}")

    return {
        "system_prompt": system_prompt,
        "peers": peers,
        "config": config,
        "raw": raw,
    }


def _extract_peers(markdown: str) -> list[str]:
    """Extract peer agent names from the '## Linked agents' section."""
    peers = []

    section_match = re.search(
        r"##\s*Linked agents\s*\n(.*?)(?=\n##|\Z)",
        markdown,
        re.DOTALL | re.IGNORECASE,
    )
    if not section_match:
        return peers

    section = section_match.group(1)

    for match in re.finditer(r"-\s*\*\*(\w+)\*\*", section):
        name = match.group(1).lower()
        if name not in peers:
            peers.append(name)

    return peers


def _extract_config(markdown: str) -> dict:
    """
    Extract configuration from the '## Config' section.

    Parses lines like:
        - key: value
        - key: value1, value2  (for list values like upstream_types)

    Returns a dict with parsed values. Recognized keys:
        scope, web, emoji, description, model, temperature,
        doc_type, output_tag, upstream_types
    """
    config = {}

    section_match = re.search(
        r"##\s*Config\s*\n(.*?)(?=\n##|\Z)",
        markdown,
        re.DOTALL | re.IGNORECASE,
    )
    if not section_match:
        return config

    section = section_match.group(1)

    for match in re.finditer(r"-\s*([\w_]+)\s*:\s*(.+)", section):
        key = match.group(1).strip().lower()
        value = match.group(2).strip()

        # Parse booleans
        if value.lower() in ("yes", "true", "on"):
            config[key] = True
        elif value.lower() in ("no", "false", "off"):
            config[key] = False
        # Parse floats
        elif key == "temperature":
            try:
                config[key] = float(value)
            except ValueError:
                config[key] = value
        # Parse comma-separated lists
        elif key == "upstream_types":
            config[key] = [v.strip() for v in value.split(",") if v.strip()]
        else:
            config[key] = value

    return config


def _clean_for_prompt(markdown: str) -> str:
    """
    Clean the markdown for use as a system prompt.
    Removes metadata sections (Config, Linked agents) and the top-level title.
    """
    # Remove the top-level title (# Agent : xxx)
    cleaned = re.sub(r"^#\s+Agent\s*:.*\n", "", markdown, count=1)

    # Remove "Linked agents" section
    cleaned = re.sub(
        r"##\s*Linked agents\s*\n.*?(?=\n##|\Z)",
        "",
        cleaned,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # Remove "Config" section (metadata, not instruction)
    cleaned = re.sub(
        r"##\s*Config\s*\n.*?(?=\n##|\Z)",
        "",
        cleaned,
        flags=re.DOTALL | re.IGNORECASE,
    )

    return cleaned.strip()


def list_available_agents() -> list[str]:
    """List all agents that have a definition file."""
    if not DEFS_DIR.exists():
        return []
    return sorted(p.stem for p in DEFS_DIR.glob("*.md"))


def discover_custom_agents() -> dict[str, dict]:
    """
    Discover custom agents defined only by their .md file.
    Returns {name: definition} for agents not in the core list.

    Core agents have dedicated Python classes with special commands.
    Custom agents use BaseAgent (scope: global) or ProjectAgent (scope: project).
    """
    custom = {}
    for agent_name in list_available_agents():
        if agent_name in CORE_AGENTS:
            continue
        definition = load_agent_definition(agent_name)
        custom[agent_name] = definition

    return custom
