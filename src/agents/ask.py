"""
Ask — Ultra-concise conversational agent.
Extends BaseAgent to provide short and direct answers.
"""

from typing import Optional
from src.agents.base import BaseAgent


class AskAgent(BaseAgent):
    """
    Agent specialized in ultra-short and direct answers.
    
    Capabilities:
    - Short answers (max 3 paragraphs)
    - No fluff, no unnecessary introductions
    - Precise and factual answers
    - Adaptability to user style
    """

    name = "ask"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def build_messages(self, user_message: str) -> list[dict]:
        """
        Build messages with a prompt adapted for short answers.
        """
        messages = super().build_messages(user_message)
        # Add instruction to limit verbosity
        if messages and messages[0]["role"] == "system":
            messages[0]["content"] = (
                messages[0]["content"] + 
                "\n\n## Response style\n"
                "Respond in an ultra-concise manner (max 3 paragraphs). "
                "Avoid unnecessary introductions, superfluous conclusions, and fluff. "
                "Be direct, precise, and factual. "
                "If the question requires a longer answer, propose an alternative."
            )
        return messages

    def handle_command(self, cmd: str) -> Optional[str]:
        """Handle agent-specific commands."""
        return super().handle_command(cmd) or ""