"""Load and merge .env + config.yaml settings."""

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


def load_config(config_path: str = "config.yaml") -> dict[str, Any]:
    """Load .env then overlay config.yaml."""
    # Load .env from project root
    env_path = Path(__file__).parent.parent / ".env"
    load_dotenv(env_path)

    # Load YAML
    yaml_path = Path(__file__).parent.parent / config_path
    if yaml_path.exists():
        with open(yaml_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    else:
        cfg = {}

    # Merge env vars as defaults (YAML wins if present)
    defaults = {
        "api_base_url": os.getenv("API_BASE_URL", ""),
        "api_key": os.getenv("API_KEY", ""),
        "retry_max_attempts": int(os.getenv("RETRY_MAX_ATTEMPTS", "8")),
        "retry_base_delay": float(os.getenv("RETRY_BASE_DELAY", "2.0")),
        "retry_max_delay": float(os.getenv("RETRY_MAX_DELAY", "120.0")),
        "workspace_path": os.getenv("WORKSPACE_PATH", "./workspace"),
    }

    # Models from env as fallback (no hardcoded defaults — must be in config.yaml or env)
    if "models" not in cfg:
        cfg["models"] = {}
    env_model_keys = {
        "heavy": "MODEL_HEAVY",
        "code": "MODEL_CODE",
        "light": "MODEL_LIGHT",
        "reasoning": "MODEL_REASONING",
        "embed": "MODEL_EMBED",
        "rerank": "MODEL_RERANK",
    }
    for key, env_var in env_model_keys.items():
        env_val = os.getenv(env_var)
        if env_val:
            cfg["models"][key] = env_val  # .env overrides config.yaml

    cfg["_defaults"] = defaults
    return cfg


def get_model_for_agent(cfg: dict, agent_name: str) -> str:
    """Resolve the model ID for a given agent."""
    agents_cfg = cfg.get("agents", {})
    agent_cfg = agents_cfg.get(agent_name, {})
    model_alias = agent_cfg.get("model", "heavy")
    return cfg["models"].get(model_alias, model_alias)


def get_agent_temperature(cfg: dict, agent_name: str) -> float:
    agents_cfg = cfg.get("agents", {})
    agent_cfg = agents_cfg.get(agent_name, {})
    return agent_cfg.get("temperature", 0.5)


def get_agent_extra_params(cfg: dict, agent_name: str) -> dict:
    """Return extra API params for a given agent (e.g. reasoning_effort).

    These are passed as **kwargs directly to the chat completion call.
    Any key not supported by the provider is silently ignored (caught in
    ResilientClient._chat_with_retry via the unknown-param error handler).

    Example config.yaml:
        agents:
          planner:
            model: reasoning
            temperature: 0.4
            extra_params:
              reasoning_effort: "high"
    """
    agents_cfg = cfg.get("agents", {})
    agent_cfg = agents_cfg.get(agent_name, {})
    return agent_cfg.get("extra_params", {})


def build_custom_dsl_context(cfg: dict) -> str:
    """Build the custom DSL context string from config.yaml.

    This is injected into agent prompts to give them knowledge
    of any domain-specific language used in the codebase.
    """
    dsl_cfg = cfg.get("custom_dsl", {})
    dsl_name = dsl_cfg.get("name", "")
    if not dsl_name:
        return ""

    parts = []
    description = dsl_cfg.get("description", "")
    if description:
        parts.append(f"{dsl_name}: {description}")

    examples = dsl_cfg.get("few_shot_examples", [])
    if examples:
        parts.append(f"\n{dsl_name} examples:")
        for ex in examples:
            parts.append(f"\nInput: {ex.get('input', '')}\nOutput:\n{ex.get('output', '')}")

    return "\n".join(parts)


def build_domain_context(cfg: dict) -> str:
    """Build the functional domain context string from config.yaml.

    This is injected into all agent prompts to give them awareness of the
    business domain, sector constraints, and key terminology of the product
    being built. Empty by default — no hardcoded domain knowledge.

    Expected config.yaml structure:
        domain:
          sector: "fintech"
          product_type: "lending platform"
          target_users: "credit analysts, compliance officers"
          description: "Optional free-form product description."
          key_constraints:
            - "RGPD compliance required on all user data"
            - "Audit trail mandatory for all financial decisions"
          glossary:
            - term: "RiskScore"
              definition: "Proprietary credit score 0-1000, threshold 650 = auto-reject"
    """
    domain_cfg = cfg.get("domain", {})
    if not domain_cfg:
        return ""

    parts = []

    sector = domain_cfg.get("sector", "")
    product_type = domain_cfg.get("product_type", "")
    if sector or product_type:
        header = "Domain context:"
        if sector and product_type:
            header += f" {product_type} ({sector})"
        elif sector:
            header += f" {sector}"
        else:
            header += f" {product_type}"
        parts.append(header)

    target_users = domain_cfg.get("target_users", "")
    if target_users:
        parts.append(f"Target users: {target_users}")

    description = domain_cfg.get("description", "")
    if description:
        parts.append(description.strip())

    constraints = domain_cfg.get("key_constraints", [])
    if constraints:
        parts.append("\nKey constraints:")
        for c in constraints:
            parts.append(f"  - {c}")

    glossary = domain_cfg.get("glossary", [])
    if glossary:
        parts.append("\nDomain glossary:")
        for entry in glossary:
            term = entry.get("term", "")
            definition = entry.get("definition", "")
            if term and definition:
                parts.append(f"  - {term}: {definition}")

    return "\n".join(parts)
