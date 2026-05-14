import sys
import os

sys.path.insert(0, os.path.dirname(__file__))


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: requires a real ANTHROPIC_API_KEY — skipped in default run",
    )
