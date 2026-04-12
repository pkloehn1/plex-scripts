"""Tests for list_pr_review_comments module."""

from __future__ import annotations

import argparse
import json

import pytest

from scripts.github.conftest import ExpectedCall, QueueRunner
from scripts.github.list_pr_review_comments import _build_parser, _run, list_review_comments, main

_COMMENTS_ARGV = ["gh", "api", "--paginate", "/repos/o/n/pulls/42/comments"]


def _sample_comment() -> dict:
    return {
        "id": 1,
        "node_id": "N1",
        "path": "f.py",
        "line": 10,
        "user": {"login": "alice"},
        "html_url": "https://x",
        "body": "fix this",
    }


# -- list_review_comments -----------------------------------------------------


def test_returns_extracted_fields() -> None:
    runner = QueueRunner([ExpectedCall(argv=_COMMENTS_ARGV, stdout=json.dumps([_sample_comment()]))])
    result = list_review_comments(runner=runner, repo="o/n", pr_number=42)
    assert len(result) == 1
    assert result[0]["author"] == "alice"
    assert result[0]["id"] == 1
    runner.assert_exhausted()


def test_skips_non_dict_items() -> None:
    runner = QueueRunner([ExpectedCall(argv=_COMMENTS_ARGV, stdout=json.dumps([_sample_comment(), "bad"]))])
    assert len(list_review_comments(runner=runner, repo="o/n", pr_number=42)) == 1


def test_handles_missing_user() -> None:
    comment = _sample_comment()
    comment["user"] = None
    runner = QueueRunner([ExpectedCall(argv=_COMMENTS_ARGV, stdout=json.dumps([comment]))])
    result = list_review_comments(runner=runner, repo="o/n", pr_number=42)
    assert result[0]["author"] is None


def test_raises_on_non_list() -> None:
    runner = QueueRunner([ExpectedCall(argv=_COMMENTS_ARGV, stdout="{}")])
    with pytest.raises(ValueError, match="Unexpected comments payload"):
        list_review_comments(runner=runner, repo="o/n", pr_number=42)


# -- _build_parser / _run / main ----------------------------------------------


def test_build_parser() -> None:
    assert isinstance(_build_parser(), argparse.ArgumentParser)


def test_run_prints_json(capsys) -> None:
    runner = QueueRunner([ExpectedCall(argv=_COMMENTS_ARGV, stdout=json.dumps([_sample_comment()]))])
    args = argparse.Namespace(repo="o/n", pr=42)
    assert _run(args, _build_parser(), runner) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["count"] == 1


def test_main_delegates(monkeypatch) -> None:
    monkeypatch.setattr("scripts.github.list_pr_review_comments.run_actionable_main", lambda **kwargs: 0)
    assert main() == 0
