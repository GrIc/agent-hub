"""Python module with dataclasses for AST fixture testing."""

from dataclasses import dataclass, field
from typing import List


@dataclass
class User:
    """A user dataclass."""
    name: str
    email: str
    tags: List[str] = field(default_factory=list)

    def add_tag(self, tag):
        self.tags.append(tag)

    def has_tag(self, tag):
        return tag in self.tags


@dataclass
class Product:
    """A product dataclass."""
    id: int
    name: str
    price: float

    def discount(self, percent):
        return self.price * (1 - percent / 100)
