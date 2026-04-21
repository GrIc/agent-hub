"""Utility functions for testing.

This is a synthetic file for testing grounding.
"""

import hashlib
from typing import Optional


def compute_hash(data: str) -> str:
    """Compute SHA-256 hash of data."""
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def format_message(message: str, level: int = 1) -> str:
    """Format a message with indentation."""
    indent = "  " * level
    return f"{indent}{message}"


def is_valid_email(email: str) -> bool:
    """Validate an email address."""
    return "@" in email and "." in email.split("@")[-1]


class Config:
    """Simple configuration class."""
    
    def __init__(self, data: Optional[dict] = None):
        self.data = data or {}
    
    def get(self, key: str, default=None):
        return self.data.get(key, default)
