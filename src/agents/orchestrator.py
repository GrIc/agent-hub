"""
Orchestrator — Agent specialized in task and pipeline coordination.
Extends BaseAgent with planning and coordination capabilities.
"""

from typing import Optional
from src.agents.base import BaseAgent


class OrchestratorAgent(BaseAgent):
    """
    Agent specialized in orchestrating complex tasks.
    
    Capabilities:
    - Complex problem decomposition into sub-tasks
    - Pipeline and workflow planning
    - Agent coordination to solve multi-step problems
    - Progress tracking and intermediate result validation
    - Error handling and alternative proposals
    - Plan optimization to minimize time and resources
    """

    name = "orchestrator"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def handle_command(self, cmd: str) -> Optional[str]:
        """Handle agent-specific commands."""
        return super().handle_command(cmd) or ""

    def build_messages(self, user_message: str) -> list[dict]:
        """
        Build messages with a prompt adapted for planning.
        """
        messages = super().build_messages(user_message)
        # Add instruction for planning
        if messages and messages[0]["role"] == "system":
            messages[0]["content"] = (
                messages[0]["content"] + 
                "\n\n## Response style\n"
                "Provide a clear and structured action plan. "
                "Break down the problem into logical steps with priorities and dependencies. "
                "Select suitable agents for each step. "
                "Propose alternatives if blockages occur. "
                "Use tables and lists to clarify the plan."
            )
        return messages