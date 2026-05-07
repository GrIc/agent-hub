"""Python module with decorators for AST fixture testing."""

from functools import wraps


def decorator(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper


class DecoratedService:
    """Service with class and method decorators."""

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value):
        self._name = value

    @staticmethod
    def static_method():
        return "static"

    @classmethod
    def class_method(cls):
        return cls()
