"""Tests for issue_upsert module."""

from __future__ import annotations

import argparse
import json
from typing import Any

import pytest

from scripts.github.conftest import make_call, make_runner
from scripts.github.issue_upsert import (
    _build_parser,
    _extract_assignee_logins,
    _extract_label_names,
    _issue_method_endpoint,
    _merge_existing_fields,
    _normalize_str_list,
    _run,
    main,
    upsert_issue,
)

_REPO = "o/n"


# -- _extract_label_names ------------------------------------------------------


def test_extract_label_names_typical() -> None:
    issue: dict[str, Any] = {
        "labels": [
            {"name": "bug"},
            {"name": " feature "},
            {"not_name": "skip"},
            "not_a_dict",
        ],
    }
    assert _extract_label_names(issue) == {"bug", "feature"}


def test_extract_label_names_missing_key() -> None:
    assert _extract_label_names({}) == set()


def test_extract_label_names_non_list() -> None:
    assert _extract_label_names({"labels": "string"}) == set()


# -- _extract_assignee_logins --------------------------------------------------


def test_extract_assignee_logins_typical() -> None:
    issue: dict[str, Any] = {
        "assignees": [
            {"login": "alice"},
            {"login": " bob "},
            {"no_login": True},
            42,
        ],
    }
    assert _extract_assignee_logins(issue) == {"alice", "bob"}


def test_extract_assignee_logins_missing() -> None:
    assert _extract_assignee_logins({}) == set()


def test_extract_assignee_logins_non_list() -> None:
    assert _extract_assignee_logins({"assignees": "string"}) == set()


# -- _normalize_str_list -------------------------------------------------------


def test_normalize_str_list_none() -> None:
    assert _normalize_str_list(None) == set()


def test_normalize_str_list_empty() -> None:
    assert _normalize_str_list([]) == set()


def test_normalize_str_list_strips() -> None:
    assert _normalize_str_list([" a ", "b", " "]) == {"a", "b"}


# -- _merge_existing_fields ----------------------------------------------------


def test_merge_existing_fields_combines() -> None:
    existing: dict[str, Any] = {
        "labels": [{"name": "bug"}],
        "assignees": [{"login": "alice"}],
    }
    labels, assignees = _merge_existing_fields(
        existing=existing,
        labels=["feature"],
        assignees=["bob"],
    )
    assert set(labels) == {"bug", "feature"}
    assert set(assignees) == {"alice", "bob"}


def test_merge_existing_fields_none_inputs() -> None:
    existing: dict[str, Any] = {
        "labels": [{"name": "bug"}],
        "assignees": [{"login": "alice"}],
    }
    labels, assignees = _merge_existing_fields(
        existing=existing,
        labels=None,
        assignees=None,
    )
    assert set(labels) == {"bug"}
    assert set(assignees) == {"alice"}


# -- _issue_method_endpoint ----------------------------------------------------


def test_issue_method_endpoint_create() -> None:
    method, endpoint = _issue_method_endpoint(
        owner="o",
        name="n",
        number=None,
        title="My Issue",
    )
    assert method == "POST"
    assert endpoint == "/repos/o/n/issues"


def test_issue_method_endpoint_edit() -> None:
    method, endpoint = _issue_method_endpoint(
        owner="o",
        name="n",
        number=42,
        title=None,
    )
    assert method == "PATCH"
    assert "/issues/42" in endpoint


def test_issue_method_endpoint_create_requires_title() -> None:
    with pytest.raises(ValueError, match="title is required"):
        _issue_method_endpoint(owner="o", name="n", number=None, title=None)


def test_issue_method_endpoint_create_rejects_empty_title() -> None:
    with pytest.raises(ValueError, match="title is required"):
        _issue_method_endpoint(owner="o", name="n", number=None, title="   ")


def test_issue_method_endpoint_edit_rejects_zero() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        _issue_method_endpoint(owner="o", name="n", number=0, title=None)


def test_issue_method_endpoint_edit_rejects_negative() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        _issue_method_endpoint(owner="o", name="n", number=-1, title=None)


# -- upsert_issue --------------------------------------------------------------


def test_upsert_issue_create_builds_correct_argv() -> None:
    issue_response = {"number": 1, "html_url": "https://github.com/o/n/issues/1"}
    runner = make_runner(
        make_call(
            [
                "gh",
                "api",
                "--method",
                "POST",
                "/repos/o/n/issues",
                "-f",
                "title=My Issue",
                "-f",
                "body=body text",
                "-f",
                "labels[]=bug",
            ],
            issue_response,
        )
    )
    result = upsert_issue(
        runner=runner,
        repo=_REPO,
        number=None,
        title="My Issue",
        body="body text",
        labels=["bug"],
        assignees=None,
    )
    assert result["number"] == 1
    runner.assert_exhausted()


def test_upsert_issue_create_with_assignees() -> None:
    issue_response = {"number": 2, "html_url": "https://github.com/o/n/issues/2"}
    runner = make_runner(
        make_call(
            [
                "gh",
                "api",
                "--method",
                "POST",
                "/repos/o/n/issues",
                "-f",
                "title=Assigned Issue",
                "-f",
                "assignees[]=alice",
                "-f",
                "assignees[]=bob",
            ],
            issue_response,
        )
    )
    result = upsert_issue(
        runner=runner,
        repo=_REPO,
        number=None,
        title="Assigned Issue",
        body=None,
        labels=None,
        assignees=["alice", "bob"],
    )
    assert result["number"] == 2
    runner.assert_exhausted()


def test_upsert_issue_edit_with_merge_existing() -> None:
    existing_issue = {
        "labels": [{"name": "existing-label"}],
        "assignees": [{"login": "existing-user"}],
    }
    upserted_issue = {"number": 5, "html_url": "https://github.com/o/n/issues/5"}
    runner = make_runner(
        make_call(
            ["gh", "api", "/repos/o/n/issues/5"],
            existing_issue,
        ),
        make_call(
            [
                "gh",
                "api",
                "--method",
                "PATCH",
                "/repos/o/n/issues/5",
                "-f",
                "labels[]=existing-label",
                "-f",
                "labels[]=new-label",
                "-f",
                "assignees[]=existing-user",
            ],
            upserted_issue,
        ),
    )
    result = upsert_issue(
        runner=runner,
        repo=_REPO,
        number=5,
        title=None,
        body=None,
        labels=["new-label"],
        assignees=None,
        merge_existing=True,
    )
    assert result["number"] == 5
    runner.assert_exhausted()


def test_upsert_issue_edit_without_merge() -> None:
    issue_response = {"number": 5, "html_url": "https://github.com/o/n/issues/5"}
    runner = make_runner(
        make_call(
            [
                "gh",
                "api",
                "--method",
                "PATCH",
                "/repos/o/n/issues/5",
                "-f",
                "title=Updated",
            ],
            issue_response,
        )
    )
    result = upsert_issue(
        runner=runner,
        repo=_REPO,
        number=5,
        title="Updated",
        body=None,
        labels=None,
        assignees=None,
        merge_existing=False,
    )
    assert result["number"] == 5
    runner.assert_exhausted()


def test_upsert_issue_raises_on_non_dict_payload() -> None:
    runner = make_runner(
        make_call(
            [
                "gh",
                "api",
                "--method",
                "PATCH",
                "/repos/o/n/issues/5",
                "-f",
                "title=T",
            ],
            [1, 2, 3],
        )
    )
    with pytest.raises(ValueError, match="Unexpected issue payload"):
        upsert_issue(
            runner=runner,
            repo=_REPO,
            number=5,
            title="T",
            body=None,
            labels=None,
            assignees=None,
        )


# -- _build_parser -------------------------------------------------------------


def test_build_parser_returns_argument_parser() -> None:
    parser = _build_parser()
    assert isinstance(parser, argparse.ArgumentParser)


def test_build_parser_has_expected_arguments() -> None:
    parser = _build_parser()
    parsed = parser.parse_args(["--repo", "o/n", "--number", "5", "--title", "T"])
    assert parsed.repo == "o/n"
    assert parsed.number == 5
    assert parsed.title == "T"


def test_build_parser_body_and_body_file_flags() -> None:
    parser = _build_parser()
    parsed = parser.parse_args(["--body", "text"])
    assert parsed.body == "text"
    parsed_file = parser.parse_args(["--body-file", "issue.md"])
    assert str(parsed_file.body_file) == "issue.md"


def test_build_parser_label_flag_repeatable() -> None:
    parser = _build_parser()
    parsed = parser.parse_args(["--label", "bug", "--label", "feature"])
    assert parsed.label == ["bug", "feature"]


def test_build_parser_assignee_flag_repeatable() -> None:
    parser = _build_parser()
    parsed = parser.parse_args(["--assignee", "alice", "--assignee", "bob"])
    assert parsed.assignee == ["alice", "bob"]


def test_build_parser_merge_existing_flag() -> None:
    parser = _build_parser()
    parsed = parser.parse_args(["--merge-existing"])
    assert parsed.merge_existing is True


def test_build_parser_json_flag() -> None:
    parser = _build_parser()
    parsed = parser.parse_args(["--json"])
    assert parsed.json is True


def test_build_parser_defaults() -> None:
    parser = _build_parser()
    parsed = parser.parse_args([])
    assert parsed.repo is None
    assert parsed.number is None
    assert parsed.title is None
    assert parsed.body is None
    assert parsed.body_file is None
    assert parsed.label is None
    assert parsed.assignee is None
    assert parsed.merge_existing is False
    assert parsed.json is False


# -- _run ----------------------------------------------------------------------


def test_run_json_output(capsys: pytest.CaptureFixture[str]) -> None:
    issue_payload = {
        "number": 3,
        "html_url": "https://github.com/o/n/issues/3",
        "title": "Test Issue",
        "state": "open",
    }
    runner = make_runner(
        make_call(
            [
                "gh",
                "api",
                "--method",
                "POST",
                "/repos/o/n/issues",
                "-f",
                "title=Test Issue",
                "-f",
                "body=body",
            ],
            issue_payload,
        )
    )
    args = argparse.Namespace(
        repo=_REPO,
        number=None,
        title="Test Issue",
        body="body",
        body_file=None,
        label=None,
        assignee=None,
        merge_existing=False,
        json=True,
    )
    exit_code = _run(args, _build_parser(), runner)
    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["number"] == 3
    assert output["url"] == "https://github.com/o/n/issues/3"
    assert output["title"] == "Test Issue"
    assert output["state"] == "open"
    runner.assert_exhausted()


def test_run_text_output(capsys: pytest.CaptureFixture[str]) -> None:
    issue_payload = {
        "number": 7,
        "html_url": "https://github.com/o/n/issues/7",
        "title": "Text Issue",
        "state": "open",
    }
    runner = make_runner(
        make_call(
            [
                "gh",
                "api",
                "--method",
                "POST",
                "/repos/o/n/issues",
                "-f",
                "title=Text Issue",
            ],
            issue_payload,
        )
    )
    args = argparse.Namespace(
        repo=_REPO,
        number=None,
        title="Text Issue",
        body=None,
        body_file=None,
        label=None,
        assignee=None,
        merge_existing=False,
        json=False,
    )
    exit_code = _run(args, _build_parser(), runner)
    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "Issue #7" in captured
    assert "https://github.com/o/n/issues/7" in captured
    runner.assert_exhausted()


def test_run_edit_with_labels_and_assignees(capsys: pytest.CaptureFixture[str]) -> None:
    issue_payload = {
        "number": 10,
        "html_url": "https://github.com/o/n/issues/10",
        "title": "Edited Issue",
        "state": "open",
    }
    runner = make_runner(
        make_call(
            [
                "gh",
                "api",
                "--method",
                "PATCH",
                "/repos/o/n/issues/10",
                "-f",
                "title=Edited Issue",
                "-f",
                "labels[]=bug",
                "-f",
                "assignees[]=alice",
            ],
            issue_payload,
        )
    )
    args = argparse.Namespace(
        repo=_REPO,
        number=10,
        title="Edited Issue",
        body=None,
        body_file=None,
        label=["bug"],
        assignee=["alice"],
        merge_existing=False,
        json=True,
    )
    exit_code = _run(args, _build_parser(), runner)
    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["number"] == 10
    runner.assert_exhausted()


def test_run_edit_with_merge_existing(capsys: pytest.CaptureFixture[str]) -> None:
    existing_issue = {
        "labels": [{"name": "old"}],
        "assignees": [{"login": "prev-user"}],
    }
    upserted_issue = {
        "number": 12,
        "html_url": "https://github.com/o/n/issues/12",
        "title": "Merged Issue",
        "state": "open",
    }
    runner = make_runner(
        make_call(
            ["gh", "api", "/repos/o/n/issues/12"],
            existing_issue,
        ),
        make_call(
            [
                "gh",
                "api",
                "--method",
                "PATCH",
                "/repos/o/n/issues/12",
                "-f",
                "labels[]=new",
                "-f",
                "labels[]=old",
                "-f",
                "assignees[]=prev-user",
            ],
            upserted_issue,
        ),
    )
    args = argparse.Namespace(
        repo=_REPO,
        number=12,
        title=None,
        body=None,
        body_file=None,
        label=["new"],
        assignee=None,
        merge_existing=True,
        json=False,
    )
    exit_code = _run(args, _build_parser(), runner)
    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "Issue #12" in captured
    runner.assert_exhausted()


# -- main ----------------------------------------------------------------------


def test_main_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scripts.github.issue_upsert.run_actionable_main", lambda **kwargs: 0)
    assert main() == 0
