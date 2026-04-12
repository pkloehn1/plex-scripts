"""Tests for list_issues module."""

from __future__ import annotations

import argparse
import json
from typing import Any

import pytest

from scripts.github.gh_cli import GhResult
from scripts.github.list_issues import (
    _build_parser,
    _extract_assignee_logins,
    _extract_label_names,
    _run,
    list_issues,
    main,
)

# -- Stub runner ---------------------------------------------------------------


class _StubRunner:
    def __init__(self, stdout: str = "[]") -> None:
        self._stdout = stdout

    def run(self, argv: list[str], *, input_text: str | None = None) -> GhResult:
        return GhResult(stdout=self._stdout, stderr="")


# -- _extract_label_names (list_issues variant) --------------------------------


def test_extract_label_names_returns_list() -> None:
    issue: dict[str, Any] = {
        "labels": [{"name": "bug"}, {"name": " docs "}],
    }
    assert _extract_label_names(issue) == ["bug", "docs"]


def test_extract_label_names_skips_non_dicts() -> None:
    assert _extract_label_names({"labels": ["not_dict", 42]}) == []


def test_extract_label_names_missing() -> None:
    assert _extract_label_names({}) == []


# -- _extract_assignee_logins (list_issues variant) ----------------------------


def test_extract_assignee_logins_returns_list() -> None:
    issue: dict[str, Any] = {
        "assignees": [{"login": "alice"}, {"login": " bob "}],
    }
    assert _extract_assignee_logins(issue) == ["alice", "bob"]


def test_extract_assignee_logins_missing() -> None:
    assert _extract_assignee_logins({}) == []


# -- list_issues ---------------------------------------------------------------


def test_list_issues_filters_prs_and_sorts() -> None:
    payload = json.dumps(
        [
            {"number": 3, "title": "Issue 3", "state": "open", "html_url": "u3"},
            {"number": 1, "title": "Issue 1", "state": "open", "html_url": "u1"},
            {"number": 2, "title": "PR", "state": "open", "pull_request": {}, "html_url": "u2"},
        ]
    )
    runner = _StubRunner(stdout=payload)
    issues = list_issues(runner=runner, repo="owner/name", state="open")
    assert len(issues) == 2
    assert issues[0]["number"] == 1
    assert issues[1]["number"] == 3


def test_list_issues_skips_malformed_items() -> None:
    payload = json.dumps(
        [
            {"number": 1, "title": "ok", "state": "open"},
            {"number": "not_int", "title": "bad"},
            {"title": "missing_number"},
            "not_a_dict",
        ]
    )
    runner = _StubRunner(stdout=payload)
    issues = list_issues(runner=runner, repo="owner/name")
    assert len(issues) == 1


def test_list_issues_raises_on_non_list() -> None:
    runner = _StubRunner(stdout='{"not": "a list"}')
    with pytest.raises(ValueError, match="expected list"):
        list_issues(runner=runner, repo="owner/name")


# -- _extract_label_names: non-dict in labels (line 43 variant) ----------------


def test_extract_label_names_non_string_labels_field() -> None:
    assert _extract_label_names({"labels": "not_a_list"}) == []


def test_extract_label_names_empty_name_skipped() -> None:
    assert _extract_label_names({"labels": [{"name": ""}, {"name": "  "}]}) == []


# -- _extract_assignee_logins: non-dict in assignees list ----------------------


def test_extract_assignee_logins_skips_non_dicts() -> None:
    assert _extract_assignee_logins({"assignees": ["not_dict", 42]}) == []


def test_extract_assignee_logins_non_list_assignees_field() -> None:
    assert _extract_assignee_logins({"assignees": "not_a_list"}) == []


def test_extract_assignee_logins_empty_login_skipped() -> None:
    assert _extract_assignee_logins({"assignees": [{"login": ""}, {"login": "  "}]}) == []


# -- _build_parser (lines 103-111) ---------------------------------------------


def test_build_parser_returns_argument_parser() -> None:
    parser = _build_parser()
    assert isinstance(parser, argparse.ArgumentParser)


def test_build_parser_accepts_state_choices() -> None:
    parser = _build_parser()
    for state_value in ("open", "closed", "all"):
        parsed = parser.parse_args(["--repo", "owner/name", "--state", state_value])
        assert parsed.state == state_value


# -- _run (lines 115-124) ------------------------------------------------------


def test_run_prints_json_output(capsys) -> None:
    payload = json.dumps([{"number": 1, "title": "Issue 1", "state": "open", "html_url": "u1"}])
    stub_runner = _StubRunner(stdout=payload)
    namespace = argparse.Namespace(repo="owner/name", state="open")
    exit_code = _run(namespace, _build_parser(), stub_runner)
    assert exit_code == 0

    output = json.loads(capsys.readouterr().out)
    assert output["repo"] == "owner/name"
    assert output["state"] == "open"
    assert output["count"] == 1
    assert len(output["issues"]) == 1


def test_run_auto_detects_repo(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "scripts.github.list_issues.current_repo",
        lambda runner: "detected/repo",
    )
    payload = json.dumps([])
    stub_runner = _StubRunner(stdout=payload)
    namespace = argparse.Namespace(repo=None, state="open")
    exit_code = _run(namespace, _build_parser(), stub_runner)
    assert exit_code == 0

    output = json.loads(capsys.readouterr().out)
    assert output["repo"] == "detected/repo"


# -- main (line 128) -----------------------------------------------------------


def test_main_delegates(monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.github.list_issues.run_actionable_main",
        lambda **kwargs: 0,
    )
    assert main() == 0
