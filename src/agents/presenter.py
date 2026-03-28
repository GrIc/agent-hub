"""Presenter agent -- produces slide deck plan."""
from src.agents.project_agent import ProjectAgent

class PresenterAgent(ProjectAgent):
    name = "presenter"
    doc_type = "deck"
    output_tag = "deck_md"
    upstream_types = ["requirements", "specifications", "roadmap", "architecture"]
