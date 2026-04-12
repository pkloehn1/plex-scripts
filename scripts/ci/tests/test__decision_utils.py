from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.ci._decision_utils import (
    DecisionResult,
    decide,
    read_changed_files,
    should_run,
)

# ---------------------------------------------------------------------------
# read_changed_files
# ---------------------------------------------------------------------------


def test_read_changed_files_returns_lines(tmp_path: Path) -> None:
    (tmp_path / "changed-files.txt").write_text("scripts/foo.py\nscripts/bar.py\n", encoding="utf-8")
    with patch("scripts.ci._decision_utils.repo_root", return_value=tmp_path):
        result = read_changed_files()
    assert result == ["scripts/foo.py", "scripts/bar.py"]


def test_read_changed_files_strips_whitespace(tmp_path: Path) -> None:
    (tmp_path / "changed-files.txt").write_text("  scripts/foo.py  \n  scripts/bar.py  \n", encoding="utf-8")
    with patch("scripts.ci._decision_utils.repo_root", return_value=tmp_path):
        result = read_changed_files()
    assert result == ["scripts/foo.py", "scripts/bar.py"]


def test_read_changed_files_skips_blank_lines(tmp_path: Path) -> None:
    (tmp_path / "changed-files.txt").write_text("scripts/foo.py\n\nscripts/bar.py\n", encoding="utf-8")
    with patch("scripts.ci._decision_utils.repo_root", return_value=tmp_path):
        result = read_changed_files()
    assert result == ["scripts/foo.py", "scripts/bar.py"]


def test_read_changed_files_empty_file_returns_empty_list(tmp_path: Path) -> None:
    (tmp_path / "changed-files.txt").write_text("", encoding="utf-8")
    with patch("scripts.ci._decision_utils.repo_root", return_value=tmp_path):
        result = read_changed_files()
    assert result == []


def test_read_changed_files_raises_file_not_found_when_missing(tmp_path: Path) -> None:
    with (
        patch("scripts.ci._decision_utils.repo_root", return_value=tmp_path),
        pytest.raises(FileNotFoundError),
    ):
        read_changed_files()


# ---------------------------------------------------------------------------
# decide
# ---------------------------------------------------------------------------


def test_decide_returns_decision_result_type() -> None:
    result = decide(["scripts/foo.py"], ("**/*.py",))
    assert isinstance(result, DecisionResult)


def test_decide_matches_single_glob() -> None:
    result = decide(["scripts/foo.py"], ("scripts/*.py",))
    assert result.should_run is True
    assert result.reason == "relevant files changed"
    assert "scripts/foo.py" in result.matched_paths


def test_decide_no_match_returns_false() -> None:
    result = decide(["README.md"], ("**/*.py",))
    assert result.should_run is False
    assert result.reason == "no relevant files changed"
    assert result.matched_paths == ()


def test_decide_empty_changed_paths_returns_false() -> None:
    result = decide([], ("**/*.py",))
    assert result.should_run is False
    assert result.matched_paths == ()


def test_decide_multiple_globs_matches_first_applicable() -> None:
    result = decide(["scripts/foo.py"], ("**/*.md", "scripts/*.py"))
    assert result.should_run is True
    assert "scripts/foo.py" in result.matched_paths


def test_decide_multiple_globs_only_one_match() -> None:
    result = decide(["README.md", "scripts/foo.py"], ("scripts/*.py",))
    assert result.should_run is True
    assert result.matched_paths == ("scripts/foo.py",)


def test_decide_multiple_paths_multiple_matches() -> None:
    result = decide(["scripts/foo.py", "scripts/bar.py"], ("scripts/*.py",))
    assert result.should_run is True
    assert set(result.matched_paths) == {"scripts/foo.py", "scripts/bar.py"}


def test_decide_path_not_double_counted_when_multiple_globs_match() -> None:
    result = decide(["scripts/foo.py"], ("scripts/*.py", "**/*.py"))
    assert result.matched_paths.count("scripts/foo.py") == 1


def test_decide_ignores_empty_string_paths() -> None:
    result = decide(["", "   ", "scripts/foo.py"], ("scripts/*.py",))
    assert result.should_run is True
    assert "" not in result.matched_paths


def test_decide_result_is_frozen() -> None:
    result = decide([], ("**/*.py",))
    with pytest.raises(FrozenInstanceError):
        result.should_run = True  # type: ignore[misc]


def test_decide_normalizes_windows_backslash_paths() -> None:
    result = decide(["scripts\\foo.py"], ("scripts/*.py",))
    assert result.should_run is True
    assert "scripts/foo.py" in result.matched_paths


def test_decide_normalizes_leading_dot_slash() -> None:
    result = decide(["./scripts/foo.py"], ("scripts/*.py",))
    assert result.should_run is True
    assert "scripts/foo.py" in result.matched_paths


# ---------------------------------------------------------------------------
# should_run
# ---------------------------------------------------------------------------


def test_should_run_returns_true_when_paths_match() -> None:
    assert should_run(["scripts/foo.py"], ("scripts/*.py",)) is True


def test_should_run_returns_false_when_no_paths_match() -> None:
    assert should_run(["README.md"], ("scripts/*.py",)) is False
