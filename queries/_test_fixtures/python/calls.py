"""Python module with various call patterns for AST fixture testing."""

import os
import sys
from pathlib import Path


def call_external():
    """Calls to external functions."""
    os.getcwd()
    len([1, 2, 3])
    Path("/tmp").exists()


class CallerService:
    """Service with internal and external calls."""

    def do_work(self):
        self.validate()
        self.process()
        call_external()

    def validate(self):
        pass

    def process(self):
        self.validate()
