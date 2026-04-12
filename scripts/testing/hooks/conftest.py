"""Shared test helpers for pre-commit hook tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import ModuleType

from _pytest.capture import CaptureFixture
from _pytest.monkeypatch import MonkeyPatch


def fake_staged_paths(paths: list[str]) -> tuple[list[Path], list[str]]:
    """Build a (paths, errors) tuple imitating _get_staged_paths()."""
    return [Path(path_str) for path_str in paths], []


def fake_file_reader(contents: dict[str, str]) -> Callable[[Path], tuple[str, None]]:
    """Build a fake _read_staged_file returning raw text."""

    def _reader(path: Path) -> tuple[str, None]:
        return contents.get(path.as_posix(), ""), None

    return _reader


def fake_file_lines_reader(contents: dict[str, str]) -> Callable[[Path], tuple[list[str], None]]:
    """Build a fake _read_staged_file returning splitlines()."""

    def _reader(path: Path) -> tuple[list[str], None]:
        text = contents.get(path.as_posix(), "")
        return text.splitlines(), None

    return _reader


def assert_staged_paths_error(mod: ModuleType, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]) -> None:
    """Verify main() reports _get_staged_paths errors."""
    monkeypatch.setattr(mod, "_get_staged_paths", lambda: ([], ["git diff --cached failed: git error"]))
    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "git diff --cached failed" in err


def assert_read_file_error(
    mod: ModuleType,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
    staged_mock_name: str,
    staged_paths: list[str],
) -> None:
    """Verify main() reports _read_staged_file errors."""
    monkeypatch.setattr(mod, staged_mock_name, lambda: fake_staged_paths(staged_paths))
    monkeypatch.setattr(mod, "_read_staged_file", lambda path: (None, f"git show :{path} failed: file not in index"))
    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "git show" in err
    assert "failed" in err
