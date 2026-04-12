"""Tests for scripts.common.paths."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.common.paths import normalize_path, repo_root


def test_repo_root_finds_pyproject_toml(monkeypatch: pytest.MonkeyPatch) -> None:
    """repo_root() finds the directory containing pyproject.toml."""
    result = repo_root()
    assert result.is_dir()
    assert (result / "pyproject.toml").exists()


def test_repo_root_walks_up_from_deeply_nested_module() -> None:
    """repo_root() walks up from deeply nested modules to find pyproject.toml."""
    # This module is at scripts/common/tests/test_paths.py (3 levels deep from scripts/)
    # repo_root() should walk up correctly regardless of nesting depth
    result = repo_root()
    assert (result / "pyproject.toml").exists()
    assert (result / "scripts" / "common" / "tests" / "test_paths.py").exists()


def test_repo_root_is_stable_across_calls() -> None:
    """repo_root() returns the same path on repeated calls."""
    first = repo_root()
    second = repo_root()
    assert first == second
    assert first.resolve() == second.resolve()


def test_repo_root_raises_when_pyproject_toml_not_found(tmp_path: Path) -> None:
    """repo_root() raises RuntimeError when no pyproject.toml is found in any ancestor."""
    # Use a deeply nested directory inside tmp_path — no pyproject.toml will be placed there
    nested_dir = tmp_path / "aaa" / "bbb" / "ccc"
    nested_dir.mkdir(parents=True)
    with patch("scripts.common.paths.Path") as mock_path_class:
        mock_file = mock_path_class.return_value.resolve.return_value
        mock_file.parent = nested_dir
        with pytest.raises(RuntimeError, match="Could not find repository root"):
            repo_root()


class TestNormalizePath:
    def test_forward_slashes_unchanged(self) -> None:
        assert normalize_path("src/utils/helper.py") == "src/utils/helper.py"

    def test_backslashes_converted(self) -> None:
        assert normalize_path("src\\utils\\helper.py") == "src/utils/helper.py"

    def test_mixed_separators(self) -> None:
        assert normalize_path("src\\utils/helper.py") == "src/utils/helper.py"

    def test_strips_leading_dot_slash(self) -> None:
        assert normalize_path("./src/helper.py") == "src/helper.py"

    def test_strips_dot_slash_after_backslash_conversion(self) -> None:
        assert normalize_path(".\\src\\helper.py") == "src/helper.py"

    def test_empty_string(self) -> None:
        assert normalize_path("") == ""

    def test_bare_filename(self) -> None:
        assert normalize_path("README.md") == "README.md"

    def test_deeply_nested_windows_path(self) -> None:
        assert (
            normalize_path(".github\\instructions\\python.instructions.md")
            == ".github/instructions/python.instructions.md"
        )
