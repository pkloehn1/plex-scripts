"""Tests for issue_fetch module."""

from __future__ import annotations

import argparse
import json

import pytest

from scripts.github.conftest import QueueRunner, make_call, make_runner
from scripts.github.issue_fetch import (
    _build_parser,
    _run,
    _safe_str_list,
    _structure_issue,
    fetch_issue,
    main,
)

_REPO = "o/n"

_RAW_ISSUE: dict[str, object] = {
    "number": 42,
    "title": "Fix the widget",
    "body": "The widget is broken.",
    "state": "open",
    "labels": [
        {"id": 1, "name": "bug", "color": "d73a4a"},
        {"id": 2, "name": "area/python", "color": "6f42c1"},
    ],
    "assignees": [
        {"login": "alice", "id": 100},
        {"login": "bob", "id": 200},
    ],
    "milestone": {"id": 1, "title": "v1.0", "state": "open"},
    "html_url": "https://github.com/o/n/issues/42",
}

_RAW_ISSUE_MINIMAL: dict[str, object] = {
    "number": 7,
    "title": "Minimal issue",
    "body": None,
    "state": "closed",
    "labels": [],
    "assignees": [],
    "milestone": None,
    "html_url": "https://github.com/o/n/issues/7",
}

_FETCH_ARGV = ["gh", "api", "/repos/o/n/issues/42"]


# -- fetch_issue ---------------------------------------------------------------


def test_fetch_issue_returns_raw_dict() -> None:
    runner = make_runner(make_call(_FETCH_ARGV, _RAW_ISSUE))
    result = fetch_issue(runner=runner, repo=_REPO, number=42)
    assert result == _RAW_ISSUE
    runner.assert_exhausted()


def test_fetch_issue_rejects_zero_number() -> None:
    with pytest.raises(ValueError, match="positive"):
        fetch_issue(runner=QueueRunner([]), repo=_REPO, number=0)


def test_fetch_issue_rejects_negative_number() -> None:
    with pytest.raises(ValueError, match="positive"):
        fetch_issue(runner=QueueRunner([]), repo=_REPO, number=-1)


def test_fetch_issue_rejects_non_dict_payload() -> None:
    runner = make_runner(make_call(_FETCH_ARGV, [1, 2, 3]))
    with pytest.raises(ValueError, match="Unexpected issue payload"):
        fetch_issue(runner=runner, repo=_REPO, number=42)


# -- _structure_issue ----------------------------------------------------------


def test_structure_issue_full() -> None:
    result = _structure_issue(_RAW_ISSUE, _REPO)
    assert result == {
        "repo": _REPO,
        "number": 42,
        "title": "Fix the widget",
        "body": "The widget is broken.",
        "state": "open",
        "labels": ["area/python", "bug"],
        "assignees": ["alice", "bob"],
        "milestone": "v1.0",
    }


def test_structure_issue_minimal() -> None:
    result = _structure_issue(_RAW_ISSUE_MINIMAL, _REPO)
    assert result["labels"] == []
    assert result["assignees"] == []
    assert result["milestone"] is None
    assert result["body"] is None


def test_structure_issue_missing_milestone_key() -> None:
    raw = {**_RAW_ISSUE, "milestone": {"id": 1}}
    result = _structure_issue(raw, _REPO)
    assert result["milestone"] is None


def test_structure_issue_skips_malformed_labels() -> None:
    raw = {**_RAW_ISSUE, "labels": [{"name": "good"}, "not-a-dict", {"id": 1}]}
    result = _structure_issue(raw, _REPO)
    assert result["labels"] == ["good"]


def test_structure_issue_skips_malformed_assignees() -> None:
    raw = {**_RAW_ISSUE, "assignees": [{"login": "alice"}, 42, {"id": 1}]}
    result = _structure_issue(raw, _REPO)
    assert result["assignees"] == ["alice"]


# -- _safe_str_list ------------------------------------------------------------


def test_safe_str_list_returns_sorted_values() -> None:
    items = [{"name": "beta"}, {"name": "alpha"}]
    assert _safe_str_list(items, "name") == ["alpha", "beta"]


def test_safe_str_list_handles_none() -> None:
    assert _safe_str_list(None, "name") == []


def test_safe_str_list_handles_non_list() -> None:
    assert _safe_str_list("not-a-list", "name") == []


def test_safe_str_list_skips_non_dict_entries() -> None:
    items = [{"name": "good"}, "bad", 42]
    assert _safe_str_list(items, "name") == ["good"]


def test_safe_str_list_skips_missing_key() -> None:
    items = [{"name": "good"}, {"other": "val"}]
    assert _safe_str_list(items, "name") == ["good"]


def test_safe_str_list_skips_non_string_values() -> None:
    items = [{"name": "good"}, {"name": 123}]
    assert _safe_str_list(items, "name") == ["good"]


def test_structure_issue_null_labels() -> None:
    raw = {**_RAW_ISSUE, "labels": None}
    result = _structure_issue(raw, _REPO)
    assert result["labels"] == []


def test_structure_issue_null_assignees() -> None:
    raw = {**_RAW_ISSUE, "assignees": None}
    result = _structure_issue(raw, _REPO)
    assert result["assignees"] == []


def test_structure_issue_non_string_milestone_title() -> None:
    raw = {**_RAW_ISSUE, "milestone": {"id": 1, "title": 42}}
    result = _structure_issue(raw, _REPO)
    assert result["milestone"] is None


# -- _build_parser / _run / main ----------------------------------------------


def test_build_parser() -> None:
    assert isinstance(_build_parser(), argparse.ArgumentParser)


def test_run_json_output(capsys: pytest.CaptureFixture[str]) -> None:
    runner = make_runner(make_call(_FETCH_ARGV, _RAW_ISSUE))
    args = argparse.Namespace(repo=_REPO, number=42, json=True)
    assert _run(args, _build_parser(), runner) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["title"] == "Fix the widget"
    assert output["labels"] == ["area/python", "bug"]


def test_run_text_output(capsys: pytest.CaptureFixture[str]) -> None:
    runner = make_runner(make_call(_FETCH_ARGV, _RAW_ISSUE))
    args = argparse.Namespace(repo=_REPO, number=42, json=False)
    assert _run(args, _build_parser(), runner) == 0
    out = capsys.readouterr().out
    assert "Issue #42" in out
    assert "Fix the widget" in out
    assert "[open]" in out


def test_main_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scripts.github.issue_fetch.run_actionable_main", lambda **kwargs: 0)
    assert main() == 0
