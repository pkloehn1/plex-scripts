"""Tests for issue_close module."""

from __future__ import annotations

import argparse
import json

import pytest

from scripts.github.conftest import ExpectedCall, QueueRunner
from scripts.github.issue_close import _build_parser, _run, close_issue, main

_REPO = "o/n"


# -- close_issue ---------------------------------------------------------------


def test_close_issue_without_comment() -> None:
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "--method",
                    "PATCH",
                    "/repos/o/n/issues/42",
                    "-f",
                    "state=closed",
                    "-f",
                    "state_reason=completed",
                ],
                stdout="{}",
            ),
        ]
    )
    result = close_issue(runner=runner, repo=_REPO, number=42)
    assert result == {"ok": True, "repo": _REPO, "number": 42, "reason": "completed", "commented": False}
    runner.assert_exhausted()


def test_close_issue_with_comment() -> None:
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=["gh", "api", "--method", "POST", "/repos/o/n/issues/42/comments", "-f", "body=Done."],
                stdout="{}",
            ),
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "--method",
                    "PATCH",
                    "/repos/o/n/issues/42",
                    "-f",
                    "state=closed",
                    "-f",
                    "state_reason=completed",
                ],
                stdout="{}",
            ),
        ]
    )
    result = close_issue(runner=runner, repo=_REPO, number=42, comment="Done.")
    assert result["commented"] is True
    runner.assert_exhausted()


def test_close_issue_with_not_planned_reason() -> None:
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "--method",
                    "PATCH",
                    "/repos/o/n/issues/1",
                    "-f",
                    "state=closed",
                    "-f",
                    "state_reason=not_planned",
                ],
                stdout="{}",
            ),
        ]
    )
    result = close_issue(runner=runner, repo=_REPO, number=1, reason="not_planned")
    assert result["reason"] == "not_planned"


def test_close_issue_skips_empty_comment() -> None:
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "--method",
                    "PATCH",
                    "/repos/o/n/issues/1",
                    "-f",
                    "state=closed",
                    "-f",
                    "state_reason=completed",
                ],
                stdout="{}",
            ),
        ]
    )
    result = close_issue(runner=runner, repo=_REPO, number=1, comment="   ")
    assert result["commented"] is False


def test_close_issue_rejects_zero_number() -> None:
    with pytest.raises(ValueError, match="positive"):
        close_issue(runner=QueueRunner([]), repo=_REPO, number=0)


def test_close_issue_rejects_bad_reason() -> None:
    with pytest.raises(ValueError, match="reason must be"):
        close_issue(runner=QueueRunner([]), repo=_REPO, number=1, reason="wontfix")


# -- _build_parser / _run / main ----------------------------------------------


def test_build_parser() -> None:
    assert isinstance(_build_parser(), argparse.ArgumentParser)


def test_run_json_output(capsys) -> None:
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "--method",
                    "PATCH",
                    "/repos/o/n/issues/1",
                    "-f",
                    "state=closed",
                    "-f",
                    "state_reason=completed",
                ],
                stdout="{}",
            ),
        ]
    )
    args = argparse.Namespace(repo=_REPO, number=1, reason="completed", comment=None, comment_file=None, json=True)
    assert _run(args, _build_parser(), runner) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True


def test_run_text_output(capsys) -> None:
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "--method",
                    "PATCH",
                    "/repos/o/n/issues/1",
                    "-f",
                    "state=closed",
                    "-f",
                    "state_reason=completed",
                ],
                stdout="{}",
            ),
        ]
    )
    args = argparse.Namespace(repo=_REPO, number=1, reason="completed", comment=None, comment_file=None, json=False)
    assert _run(args, _build_parser(), runner) == 0
    assert "Closed issue" in capsys.readouterr().out


def test_main_delegates(monkeypatch) -> None:
    monkeypatch.setattr("scripts.github.issue_close.run_actionable_main", lambda **kwargs: 0)
    assert main() == 0
