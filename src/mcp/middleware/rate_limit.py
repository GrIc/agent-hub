"""Rate‑limit middleware for MCP tools.

When enabled via configuration, the middleware enforces a per‑tool request
rate limit (requests per minute). The limits are defined in ``config.yaml``
under ``mcp.rate_limit`` with a ``default_per_minute`` value and optional
per‑tool overrides.

If a request exceeds the allowed rate, the function returns an error string;
otherwise it returns ``None`` to indicate success.
"""

import time
from typing import Optional

# Load configuration lazily to avoid circular imports.
from src.config import load_config

# In‑memory state tracking request counts per tool.
# Structure: {tool_name: (window_start_timestamp, request_count)}
_RATE_LIMIT_STATE: dict[str, tuple[float, int]] = {}

# Cache the configuration after the first load.
_CONFIG_CACHE: Optional[dict] = None


def _get_config() -> dict:
    global _CONFIG_CACHE
    if _CONFIG_CACHE is None:
        _CONFIG_CACHE = load_config()
    return _CONFIG_CACHE


def enforce_rate_limit(context: dict, tool_name: str) -> str | None:
    """Enforce per‑tool rate limiting.

    ``context`` is the request context (may contain client metadata). The
    function returns ``None`` if the request is within the allowed rate, or a
    descriptive error string (e.g. ``"rate limit exceeded"``) if the limit is
    exceeded.
    """
    cfg = _get_config()
    mcp_cfg = cfg.get("mcp", {})
    rl_cfg = mcp_cfg.get("rate_limit", {})
    # If no rate‑limit config, treat as unlimited.
    if not rl_cfg:
        return None

    default_limit = rl_cfg.get("default_per_minute", 60)
    per_tool_overrides = rl_cfg.get("per_tool", {})
    limit = per_tool_overrides.get(tool_name, default_limit)

    now = time.time()
    window_start, count = _RATE_LIMIT_STATE.get(tool_name, (now, 0))
    # If the current window is older than 60 seconds, reset.
    if now - window_start >= 60:
        window_start = now
        count = 0
    if count >= limit:
        # Rate limit exceeded.
        return f"rate limit exceeded for tool '{tool_name}' (limit {limit}/minute)"
    # Increment count and store.
    _RATE_LIMIT_STATE[tool_name] = (window_start, count + 1)
    return None
