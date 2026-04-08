"""
Architect — Agent specialized in designing technical architectures.
Extends BaseAgent with design and planning capabilities.
"""

from typing import Optional
from src.agents.base import BaseAgent


class ArchitectAgent(BaseAgent):
    """
    Agent specialized in designing technical architectures.
    
    Capabilities:
    - Functional requirements analysis
    - Architecture design (monolithic, microservices, event-driven, etc.)
    - Technology selection
    - Technical documentation (Mermaid, Markdown)
    - Trade-off validation (performance, security, scalability)
    """

    name = "architect"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def handle_command(self, cmd: str) -> Optional[str]:
        """Handle agent-specific commands."""
        return super().handle_command(cmd) or ""

    def post_process(self, response: str) -> str:
        """Post-process the response for the architect."""
        # Add Mermaid diagrams if needed
        return response