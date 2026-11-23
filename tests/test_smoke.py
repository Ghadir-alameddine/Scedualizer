"""Smoke tests: verify the package imports and the modular layout is intact."""

from __future__ import annotations

import importlib
import pathlib

import pytest

import scedualizer

# Sub-packages expected by the modular architecture (ROADMAP.md, Phase 0).
_EXPECTED_SUBPACKAGES = (
    "config",
    "data",
    "data.db",
    "data.models",
    "auth",
    "services",
    "apps",
)


def test_package_imports() -> None:
    """The top-level package and its ``main`` entry point are importable."""
    assert scedualizer.main is not None
    assert callable(scedualizer.main)


@pytest.mark.parametrize("name", _EXPECTED_SUBPACKAGES)
def test_subpackage_imports(name: str) -> None:
    """Each documented sub-package imports cleanly."""
    module = importlib.import_module(f"scedualizer.{name}")
    assert module is not None


def test_package_directory_exists() -> None:
    """The source package lives where the build system expects it."""
    pkg_root = pathlib.Path(scedualizer.__file__).resolve().parent
    assert pkg_root.is_dir()
