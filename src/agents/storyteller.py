"""Storyteller agent — produces a techno-functional synthesis document."""
from src.agents.project_agent import ProjectAgent


class StorytellerAgent(ProjectAgent):
    name = "storyteller"
    doc_type = "synthesis"
    output_tag = "synthesis_md"
    upstream_types = ["requirements", "specifications", "roadmap"]