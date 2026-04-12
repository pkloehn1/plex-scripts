"""Repository-root discovery and cross-platform path utilities."""

from __future__ import annotations

from pathlib import Path


def normalize_path(path: str) -> str:
    """Collapse Windows separators and strip leading ``./``.

    All paths stored as strings in result dataclasses, config comparisons,
    and log output should pass through this function so that forward-slash
    paths work identically on Windows and POSIX systems.
    """
    return path.replace("\\", "/").removeprefix("./")


def repo_root() -> Path:
    """Walk upward from this file to find the repository root.

    Looks for ``pyproject.toml`` as the marker.  This replaces the fragile
    ``Path(__file__).resolve().parents[N]`` pattern that breaks when a
    caller is moved to a different directory depth.
    """
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            return current
        current = current.parent
    raise RuntimeError("Could not find repository root (no pyproject.toml in ancestors)")
