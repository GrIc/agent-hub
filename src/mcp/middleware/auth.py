"""Authentication middleware for MCP tools.

When enabled via configuration, the middleware enforces a bearer token
provided in the `Authorization` header of the request. The token value
is read from an environment variable (default ``MCP_BEARER_TOKEN``) as
configured in ``config.yaml`` under ``mcp.auth.token_env``.

If authentication is disabled, the middleware is a no‑op.
"""

import os
from typing import Optional

# Load configuration lazily to avoid circular imports; we import the
# ``load_config`` helper from ``src.config`` which merges ``.env`` and
# ``config.yaml``.
from src.config import load_config

# Cache the configuration after the first load to avoid repeated I/O.
_CONFIG_CACHE: Optional[dict] = None

def _get_config() -> dict:
    global _CONFIG_CACHE
    if _CONFIG_CACHE is None:
        _CONFIG_CACHE = load_config()
    return _CONFIG_CACHE


def enforce_auth(context: dict) -> str | None:
    """Enforce authentication based on the request ``context``.

    The ``context`` dictionary is expected to contain a ``headers`` mapping
    (case‑insensitive) and optionally other request metadata. If authentication
    is enabled and the token is missing or invalid, a descriptive error string
    is returned; otherwise ``None`` is returned to indicate success.
    """
    cfg = _get_config()
    mcp_cfg = cfg.get("mcp", {})
    auth_cfg = mcp_cfg.get("auth", {})
    if not auth_cfg.get("enabled", False):
        # Auth disabled – nothing to enforce.
        return None

    # Resolve the environment variable name that holds the expected token.
    token_env_name = auth_cfg.get("token_env", "MCP_BEARER_TOKEN")
    expected_token = os.getenv(token_env_name)
    if not expected_token:
        # Configuration error – token not set in the environment.
        return "authentication token not configured"

    # Extract the Authorization header. Header keys may be capitalised
    # differently depending on the client, so we perform a case‑insensitive
    # lookup.
    headers = context.get("headers", {})
    auth_header = None
    for key, value in headers.items():
        if key.lower() == "authorization":
            auth_header = value
            break
    if not auth_header:
        return "missing Authorization header"

    # Expected format: "Bearer <token>"
    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return "invalid Authorization header format"
    provided_token = parts[1]
    if provided_token != expected_token:
        return "invalid authentication token"

    # Authentication succeeded – optionally store the token in the context for
    # downstream middleware (e.g., rate limiting).
    context["auth_token"] = provided_token
    return None
