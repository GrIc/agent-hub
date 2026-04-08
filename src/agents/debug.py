"""
Debug — Expert debugger specialized in error analysis and debugging.
Extends BaseAgent with diagnostic and problem-solving capabilities.
"""

from typing import Optional
from src.agents.base import BaseAgent


class DebugAgent(BaseAgent):
    """
    Agent specialized in debugging and error analysis.
    
    Capabilities:
    - Log and error trace analysis
    - Root cause diagnosis
    - Clear and testable fix proposals
    - Bug and solution documentation
    - Recommendations to avoid recurrences
    """

    name = "debug"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def handle_command(self, cmd: str) -> Optional[str]:
        """Handle agent-specific commands."""
        return super().handle_command(cmd) or ""

    def post_process(self, response: str) -> str:
        """Post-process the response for debugging."""
        # Add clear sections for diagnosis
        if "Diagnosis" not in response:
            response = f"## Diagnosis\n\n{response}"
        if "Solution" not in response:
            response = f"{response}\n\n## Solution\n\n[Proposed solution here]"
        return response