"""Build auto-generated Markdown documentation for MCP tools.

Scans the registered MCP tools via ``discover_tools`` from
:mod:`src.mcp.registry` and writes a comprehensive Markdown reference
file at ``docs/mcp/tools.md``.

Usage
-----
::

    python scripts/build_mcp_docs.py

The script logs progress to the module-level logger
``mcp.docs`` and produces a single output file containing one section
per tool, sorted alphabetically.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, Dict

# ------------------------------------------------------------------
# Logging setup
# ------------------------------------------------------------------
logger = logging.getLogger("mcp.docs")

# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------
OUTPUT_PATH = os.path.join("docs", "mcp", "tools.md")

# Attributes rendered as a bullet list (extra metadata beyond the
# core schema fields).
EXTRA_ATTRIBUTES = (
    "requires_citations",
    "auth_required",
    "rate_limit_per_minute",
)


# ------------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------------

def _json_block(data: Any, label: str = "json") -> str:
    """Return a fenced Markdown code block containing *data* as JSON.

    Parameters
    ----------
    data:
        Any JSON-serialisable object.
    label:
        Language label for the fence (default ``"json"``).

    Returns
    -------
    str
        The fenced code block string.
    """
    return f"```{label}\n{json.dumps(data, indent=2, ensure_ascii=False)}\n```\n"


def _render_tool(tool_name: str, tool: Any) -> str:
    """Render a single tool's documentation as a Markdown string.

    Parameters
    ----------
    tool_name:
        The tool's display name (used as the heading).
    tool:
        A :class:`src.mcp.base.BaseTool` instance.

    Returns
    -------
    str
        Markdown content for this tool.
    """
    lines: list[str] = []

    # Sub-heading
    lines.append(f"## {tool_name}\n")

    # Description
    description = getattr(tool, "description", "")
    if description:
        lines.append(f"{description}\n")

    # Input schema
    input_schema = getattr(tool, "input_schema", None)
    if input_schema is not None:
        lines.append("### Input Schema\n")
        lines.append(_json_block(input_schema))

    # Output schema
    output_schema = getattr(tool, "output_schema", None)
    if output_schema is not None:
        lines.append("### Output Schema\n")
        lines.append(_json_block(output_schema))

    # Examples
    examples = getattr(tool, "examples", None)
    if examples:
        lines.append("### Examples\n")
        for idx, example in enumerate(examples, start=1):
            lines.append(f"#### Example {idx}\n")
            input_data = example.get("input")
            if input_data is not None:
                lines.append("**Input**\n")
                lines.append(_json_block(input_data))
            output_data = example.get("output")
            if output_data is not None:
                lines.append("**Output**\n")
                lines.append(_json_block(output_data))

    # Extra attributes
    extra_lines: list[str] = []
    for attr in EXTRA_ATTRIBUTES:
        value = getattr(tool, attr, None)
        if value is not None:
            extra_lines.append(f"- `{attr}`: `{value}`")
    if extra_lines:
        lines.append("### Attributes\n")
        lines.extend(extra_lines)
        lines.append("")

    return "\n".join(lines)


def generate_docs(
    tools: Dict[str, Any],
    output_path: str = OUTPUT_PATH,
) -> str:
    """Generate the full Markdown documentation and write it to *output_path*.

    Parameters
    ----------
    tools:
        Mapping of tool name to :class:`src.mcp.base.BaseTool` instance,
        typically returned by :func:`src.mcp.registry.discover_tools`.
    output_path:
        File path where the Markdown file will be written.

    Returns
    -------
    str
        The full Markdown content that was written.
    """
    logger.info("Generating MCP tools documentation for %d tool(s).", len(tools))

    # Build the Markdown content.
    md_parts: list[str] = []
    md_parts.append("# MCP Tools Reference\n")

    if not tools:
        md_parts.append(
            "> **Note**: No tools are currently registered. "
            "Add tool classes to the ``src.mcp.tools`` package and "
            "re-run this script to generate documentation.\n"
        )
    else:
        for name in sorted(tools.keys()):
            tool = tools[name]
            md_parts.append(_render_tool(name, tool))
            md_parts.append("")  # blank line between tools

    content = "\n".join(md_parts)

    # Ensure the output directory exists.
    out_dir = os.path.dirname(output_path)
    if out_dir:
        try:
            os.makedirs(out_dir, exist_ok=True)
            logger.debug("Ensured output directory exists: %s", out_dir)
        except OSError as exc:
            logger.error("Failed to create output directory '%s': %s", out_dir, exc)
            raise

    # Write the file.
    try:
        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(content)
        logger.info("Documentation written to %s", output_path)
    except IOError as exc:
        logger.error("Failed to write documentation to '%s': %s", output_path, exc)
        raise

    return content


# ------------------------------------------------------------------
# Main entry point
# ------------------------------------------------------------------

def main() -> None:
    """Run the documentation generation when executed directly.

    Discovers tools via :func:`src.mcp.registry.discover_tools`, handles
    import errors gracefully, and exits with a non-zero status on failure.
    """
    # Attempt to import discover_tools.
    try:
        from src.mcp.registry import discover_tools  # noqa: PLC0414
    except ImportError as exc:
        logger.error(
            "Failed to import discover_tools from src.mcp.registry: %s",
            exc,
        )
        sys.exit(1)

    # Discover tools.
    try:
        tools = discover_tools()
    except Exception as exc:
        logger.error("Error during tool discovery: %s", exc)
        sys.exit(1)

    if not tools:
        logger.warning("No tools discovered. A placeholder note will be written.")

    # Generate and write the documentation.
    try:
        generate_docs(tools)
    except Exception as exc:
        logger.error("Documentation generation failed: %s", exc)
        sys.exit(1)

    logger.info("Documentation generation complete.")


if __name__ == "__main__":
    main()
