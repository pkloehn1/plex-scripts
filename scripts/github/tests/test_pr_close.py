"""Tests for pr_close module."""

from __future__ import annotations

import argparse
import json

import pytest

from scripts.github.conftest import ExpectedCall, QueueRunner
from scripts.github.pr_close import _build_parser, _run, close_pr, main

_REPO = "o/n"


# -- close_pr ------------------------------------------------------------------


def test_close_pr_minimal() -> None:
    runner = QueueRunner(
        [
            ExpectedCall(argv=["gh", "pr", "close", "42", "--repo", _REPO], stdout=""),
        ]
    )
    result = close_pr(runner=runner, repo=_REPO, pr_number=42)
    assert result == {"ok": True, "repo": _REPO, "pr": 42, "delete_branch": False, "commented": False}
    runner.assert_exhausted()


def test_close_pr_with_comment() -> None:
    runner = QueueRunner(
        [
            ExpectedCall(argv=["gh", "pr", "comment", "42", "--repo", _REPO, "--body", "Done."], stdout=""),
            ExpectedCall(argv=["gh", "pr", "close", "42", "--repo", _REPO], stdout=""),
        ]
    )
    result = close_pr(runner=runner, repo=_REPO, pr_number=42, comment="Done.")
    assert result["commented"] is True
    runner.assert_exhausted()


def test_close_pr_with_delete_branch() -> None:
    runner = QueueRunner(
        [
            ExpectedCall(argv=["gh", "pr", "close", "42", "--repo", _REPO, "--delete-branch"], stdout=""),
        ]
    )
    result = close_pr(runner=runner, repo=_REPO, pr_number=42, delete_branch=True)
    assert result["delete_branch"] is True
    runner.assert_exhausted()


def test_close_pr_skips_empty_comment() -> None:
    runner = QueueRunner(
        [
            ExpectedCall(argv=["gh", "pr", "close", "1", "--repo", _REPO], stdout=""),
        ]
    )
    result = close_pr(runner=runner, repo=_REPO, pr_number=1, comment="   ")
    assert result["commented"] is False


def test_close_pr_rejects_zero() -> None:
    with pytest.raises(ValueError, match="positive"):
        close_pr(runner=QueueRunner([]), repo=_REPO, pr_number=0)


def test_close_pr_rejects_bad_repo() -> None:
    with pytest.raises(ValueError, match="owner/name"):
        close_pr(runner=QueueRunner([]), repo="badrepo", pr_number=1)


# -- _build_parser / _run / main ----------------------------------------------


def test_build_parser() -> None:
    assert isinstance(_build_parser(), argparse.ArgumentParser)


def test_run_json_output(capsys) -> None:
    runner = QueueRunner(
        [
            ExpectedCall(argv=["gh", "pr", "close", "1", "--repo", _REPO], stdout=""),
        ]
    )
    args = argparse.Namespace(repo=_REPO, pr=1, delete_branch=False, comment=None, json=True)
    assert _run(args, _build_parser(), runner) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True


def test_run_text_output(capsys) -> None:
    runner = QueueRunner(
        [
            ExpectedCall(argv=["gh", "pr", "close", "1", "--repo", _REPO], stdout=""),
        ]
    )
    args = argparse.Namespace(repo=_REPO, pr=1, delete_branch=False, comment=None, json=False)
    assert _run(args, _build_parser(), runner) == 0
    assert "Closed PR" in capsys.readouterr().out


def test_main_delegates(monkeypatch) -> None:
    monkeypatch.setattr("scripts.github.pr_close.run_actionable_main", lambda **kwargs: 0)
    assert main() == 0
