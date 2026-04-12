"""Tests for pr_overview module."""

from __future__ import annotations

import argparse
import json

import pytest

from scripts.github.conftest import ExpectedCall, QueueRunner
from scripts.github.pr_overview import _build_parser, _run, main, pr_overview

_VIEW_ARGV = [
    "gh",
    "pr",
    "view",
    "42",
    "--repo",
    "owner/name",
    "--json",
    "number,url,title,mergeable,reviewDecision,headRefName,baseRefName,commits,statusCheckRollup",
]


def _make_payload() -> dict:
    return {
        "number": 42,
        "url": "https://github.com/owner/name/pull/42",
        "title": "feat: thing",
        "mergeable": "MERGEABLE",
        "reviewDecision": "APPROVED",
        "headRefName": "feat/thing",
        "baseRefName": "main",
        "commits": [],
        "statusCheckRollup": [],
    }


# -- pr_overview ---------------------------------------------------------------


def test_pr_overview_returns_dict() -> None:
    payload = _make_payload()
    runner = QueueRunner([ExpectedCall(argv=_VIEW_ARGV, stdout=json.dumps(payload))])
    result = pr_overview(runner=runner, repo="owner/name", pr_number=42)
    assert result == payload
    runner.assert_exhausted()


def test_pr_overview_raises_on_non_dict() -> None:
    runner = QueueRunner([ExpectedCall(argv=_VIEW_ARGV, stdout=json.dumps([1, 2]))])
    with pytest.raises(ValueError, match="Unexpected gh pr view payload"):
        pr_overview(runner=runner, repo="owner/name", pr_number=42)


# -- _build_parser -------------------------------------------------------------


def test_build_parser_returns_argument_parser() -> None:
    parser = _build_parser()
    assert isinstance(parser, argparse.ArgumentParser)


# -- _run ----------------------------------------------------------------------


def test_run_prints_json_and_returns_zero(capsys) -> None:
    payload = _make_payload()
    runner = QueueRunner([ExpectedCall(argv=_VIEW_ARGV, stdout=json.dumps(payload))])
    args = argparse.Namespace(repo="owner/name", pr=42)
    exit_code = _run(args, _build_parser(), runner)
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == payload
    runner.assert_exhausted()


# -- main ----------------------------------------------------------------------


def test_main_delegates_to_run_actionable_main(monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.github.pr_overview.run_actionable_main",
        lambda **kwargs: 0,
    )
    assert main() == 0
