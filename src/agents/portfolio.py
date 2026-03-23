"""Portfolio agent -- aggregates notes into requirements."""
from src.agents.project_agent import ProjectAgent

class PortfolioAgent(ProjectAgent):
    name = "portfolio"
    doc_type = "requirements"
    output_tag = "requirements_md"
    upstream_types = []
