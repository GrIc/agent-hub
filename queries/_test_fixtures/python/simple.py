"""Simple Python module for AST fixture testing."""


class SimpleService:
    """A simple service class."""

    def __init__(self, name):
        self.name = name

    def get_name(self):
        return self.name

    def set_name(self, name):
        self.name = name


def standalone_function(x):
    return x * 2
