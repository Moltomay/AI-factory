"""Smoke tests for the bootstrap package layout (acceptance criterion AC1)."""

import importlib

PACKAGE_LAYERS = [
    "ai_factory",
    "ai_factory.domain",
    "ai_factory.application",
    "ai_factory.infrastructure",
    "ai_factory.interfaces",
]


def test_spec00_ac1_package_and_layers_are_importable() -> None:
    """AC1: ai_factory and its four layers import cleanly from the repo root."""
    for module_name in PACKAGE_LAYERS:
        assert importlib.import_module(module_name)
