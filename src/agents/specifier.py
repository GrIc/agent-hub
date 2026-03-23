"""Specifier agent -- translates requirements into technical specifications."""
from src.agents.project_agent import ProjectAgent

class SpecifierAgent(ProjectAgent):
    name = "specifier"
    doc_type = "specifications"
    output_tag = "specifications_md"
    upstream_types = ["requirements"]
