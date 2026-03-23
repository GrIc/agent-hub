"""Planner agent -- breaks specifications into roadmap with milestones and tasks."""
from src.agents.project_agent import ProjectAgent

class PlannerAgent(ProjectAgent):
    name = "planner"
    doc_type = "roadmap"
    output_tag = "roadmap_md"
    upstream_types = ["requirements", "specifications"]
