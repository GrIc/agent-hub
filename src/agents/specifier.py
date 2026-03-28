"""
Specifier agent — translates requirements into technical specifications
and architectural decisions. Merges the former architect role.
"""
from src.agents.project_agent import ProjectAgent


class SpecifierAgent(ProjectAgent):
    name = "specifier"
    doc_type = "specifications"
    output_tag = "specifications_md"
    upstream_types = ["requirements"]