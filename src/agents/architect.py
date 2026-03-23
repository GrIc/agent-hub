"""Architect agent -- produces fullstack technical architecture with diagrams."""
from src.agents.project_agent import ProjectAgent

class ArchitectAgent(ProjectAgent):
    name = "architect"
    doc_type = "architecture"
    output_tag = "architecture_md"
    upstream_types = ["requirements", "specifications", "roadmap"]
