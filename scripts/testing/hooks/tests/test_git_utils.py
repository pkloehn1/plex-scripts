"""Tests for scripts.testing.hooks.git_utils."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.common.git_runner import GitResult
from scripts.testing.hooks import git_utils


def test_run_git_delegates_to_git_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_git() delegates to scripts.common.git_runner.run_git()."""
    calls: list[list[str]] = []

    def fake_run_git(args: list[str]) -> GitResult:
        calls.append(args)
        return GitResult(returncode=0, stdout="output", stderr="")

    monkeypatch.setattr("scripts.common.git_runner.run_git", fake_run_git)

    result = git_utils.run_git(["status", "--short"])

    assert len(calls) == 1, "Expected exactly one call to run_git"
    assert calls[0] == ["status", "--short"]
    assert result.returncode == 0
    assert result.stdout == "output"
    assert result.stderr == ""


def test_run_git_returns_git_result_on_success() -> None:
    """run_git() returns GitResult on successful command."""
    # Use a real git command that should always work
    result = git_utils.run_git(["--version"])

    assert isinstance(result, GitResult)
    assert result.returncode == 0
    assert "git version" in result.stdout.lower()
    assert result.stderr == ""


def test_run_git_returns_git_result_on_failure() -> None:
    """run_git() returns GitResult with non-zero returncode on failure."""
    # Use an invalid git command
    result = git_utils.run_git(["invalid-subcommand-xyz"])

    assert isinstance(result, GitResult)
    assert result.returncode != 0
    assert result.stderr != ""


# -- get_staged_paths --


def test_get_staged_paths_returns_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_staged_paths() returns parsed paths on success."""
    monkeypatch.setattr(
        git_utils,
        "run_git",
        lambda _args: GitResult(returncode=0, stdout="README.md\nscripts/ci/main.py\n", stderr=""),
    )
    paths, errors = git_utils.get_staged_paths()
    assert errors == []
    assert paths == [Path("README.md"), Path("scripts/ci/main.py")]


def test_get_staged_paths_with_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_staged_paths() appends path filters to the git command."""
    captured_args: list[list[str]] = []

    def fake_run(args: list[str]) -> GitResult:
        captured_args.append(args)
        return GitResult(returncode=0, stdout="scripts/ci/main.py\n", stderr="")

    monkeypatch.setattr(git_utils, "run_git", fake_run)
    paths, errors = git_utils.get_staged_paths("scripts/ci/")
    assert errors == []
    assert paths == [Path("scripts/ci/main.py")]
    assert "--" in captured_args[0]
    assert "scripts/ci/" in captured_args[0]


def test_get_staged_paths_git_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_staged_paths() returns errors when git fails."""
    monkeypatch.setattr(
        git_utils,
        "run_git",
        lambda _args: GitResult(returncode=1, stdout="", stderr="fatal: not a git repo"),
    )
    paths, errors = git_utils.get_staged_paths()
    assert paths == []
    assert len(errors) == 1
    assert "git diff --cached failed" in errors[0]


def test_get_staged_paths_skips_blank_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_staged_paths() skips blank lines in git output."""
    monkeypatch.setattr(
        git_utils,
        "run_git",
        lambda _args: GitResult(returncode=0, stdout="README.md\n\n  \nother.py\n", stderr=""),
    )
    paths, _ = git_utils.get_staged_paths()
    assert paths == [Path("README.md"), Path("other.py")]


# -- read_staged_file --


def test_read_staged_file_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """read_staged_file() returns file content on success."""
    monkeypatch.setattr(
        git_utils,
        "run_git",
        lambda _args: GitResult(returncode=0, stdout="file content here", stderr=""),
    )
    content, err = git_utils.read_staged_file(Path("README.md"))
    assert content == "file content here"
    assert err is None


def test_read_staged_file_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """read_staged_file() returns error when git show fails."""
    monkeypatch.setattr(
        git_utils,
        "run_git",
        lambda _args: GitResult(returncode=1, stdout="", stderr="file not in index"),
    )
    content, err = git_utils.read_staged_file(Path("missing.py"))
    assert content is None
    assert err is not None
    assert "git show" in err
    assert "failed" in err
