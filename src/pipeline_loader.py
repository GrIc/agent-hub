"""
Pipeline loader — Parse pipeline definition markdown files.

Usage:
    from src.pipeline_loader import discover_pipelines, load_pipeline

    pipelines = discover_pipelines()
    print(pipelines["feature-dev"].steps)
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class PipelineStep:
    agent: str
    label: str
    description: str
    doc_type: Optional[str] = None


@dataclass
class PipelineDefinition:
    id: str
    name: str
    icon: str
    description: str
    scope: str
    openwebui: bool
    steps: list[PipelineStep] = field(default_factory=list)


def load_pipeline(path: Path) -> PipelineDefinition:
    """
    Parse a pipeline markdown file and return a PipelineDefinition.

    Expected format:
        # Pipeline: Feature Development

        ## Config
        - id: feature-dev
        - description: ...
        - openwebui: yes
        - icon: 🔄
        - scope: project

        ## Steps

        ### 1. portfolio — Requirements
        Transform notes into functional requirements.
        output: requirements

        ### 2. specifier — Specifications + Architecture
        ...
        output: specifications

        ## Commands
        - /finalize — ...
    """
    content = path.read_text(encoding="utf-8", errors="replace")
    lines = content.split("\n")

    # Defaults
    pipeline_id = ""
    name = ""
    icon = ""
    description = ""
    scope = ""
    openwebui = False
    steps: list[PipelineStep] = []

    # Parse title
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# Pipeline:"):
            name = stripped[len("# Pipeline:"):].strip()
            break

    # Parse sections
    current_section = ""
    current_agent: Optional[str] = None
    current_label: Optional[str] = None
    step_lines: list[str] = []

    def _save_step(agent: str, label: str, lines: list[str]) -> None:
        """Helper to finalize a step and append it."""
        desc = "\n".join(lines).strip()
        doc_type = None
        for sl in lines:
            if sl.startswith("output:"):
                doc_type = sl[len("output:"):].strip() or None
        steps.append(PipelineStep(
            agent=agent,
            label=label,
            description=desc,
            doc_type=doc_type,
        ))

    for line in lines:
        stripped = line.strip()

        # Detect section headers
        if stripped.startswith("## Config"):
            current_section = "config"
            continue
        elif stripped.startswith("## Steps"):
            current_section = "steps"
            continue
        elif stripped.startswith("## Commands"):
            current_section = "commands"
            continue
        elif stripped.startswith("## "):
            current_section = "other"
            continue

        if current_section == "config":
            if stripped.startswith("- id:"):
                pipeline_id = stripped[len("- id:"):].strip()
            elif stripped.startswith("- description:"):
                description = stripped[len("- description:"):].strip()
            elif stripped.startswith("- openwebui:"):
                val = stripped[len("- openwebui:"):].strip().lower()
                openwebui = val in ("yes", "true", "1")
            elif stripped.startswith("- icon:"):
                icon = stripped[len("- icon:"):].strip()
            elif stripped.startswith("- scope:"):
                scope = stripped[len("- scope:"):].strip()

        elif current_section == "steps":
            # Detect step header: ### 1. portfolio — Requirements
            step_match = re.match(r"^###\s+\d+\.\s+(\S+)\s*[—-]\s*(.+)$", stripped)
            if step_match:
                # Save previous step if any
                if current_agent is not None and step_lines:
                    _save_step(current_agent, current_label or "", step_lines)

                current_agent = step_match.group(1)
                current_label = step_match.group(2).strip()
                step_lines = []
            elif current_agent is not None and stripped and not stripped.startswith("#"):
                step_lines.append(stripped)

    # Don't forget the last step
    if current_agent is not None and step_lines:
        _save_step(current_agent, current_label or "", step_lines)

    return PipelineDefinition(
        id=pipeline_id or path.stem,
        name=name or path.stem,
        icon=icon,
        description=description,
        scope=scope,
        openwebui=openwebui,
        steps=steps,
    )


def discover_pipelines(
    pipelines_dir: Path = Path("agents/pipelines"),
) -> dict[str, PipelineDefinition]:
    """
    Discover and load all pipeline definitions from the given directory.

    Returns:
        {pipeline_id: PipelineDefinition}
    """
    result: dict[str, PipelineDefinition] = {}
    if not pipelines_dir.exists():
        return result

    for f in sorted(pipelines_dir.glob("*.md")):
        try:
            pipeline = load_pipeline(f)
            result[pipeline.id] = pipeline
        except Exception as e:
            # Skip malformed files silently
            pass

    return result
