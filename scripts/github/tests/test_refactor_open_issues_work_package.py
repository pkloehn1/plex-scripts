"""Tests for refactor_open_issues_work_package module."""

from __future__ import annotations

import argparse
import json
from typing import Any

import pytest

from scripts.github.gh_cli import GhCliError, GhResult
from scripts.github.refactor_open_issues_work_package import (
    _build_parser,
    _normalize_body,
    _parse_args,
    build_work_package_body,
    main,
    refactor_open_issues,
)

_REPO = "o/n"
_MODULE = "scripts.github.refactor_open_issues_work_package"


# -- Stub runner (satisfies GhRunner protocol, never actually called) ----------


class _NullRunner:
    """Stub runner that fails if called — tests monkeypatch the callees."""

    def run(self, argv: list[str], *, input_text: str | None = None) -> GhResult:
        raise AssertionError(f"Unexpected runner call: {argv!r}")


_RUNNER = _NullRunner()


# -- _normalize_body -----------------------------------------------------------


def test_normalize_body_strips_trailing_whitespace_per_line() -> None:
    raw_text = "line one   \nline two\t\nline three"
    result = _normalize_body(raw_text)
    assert result == "line one\nline two\nline three"


def test_normalize_body_strips_leading_and_trailing_newlines() -> None:
    raw_text = "\n\n  hello  \n  world  \n\n"
    result = _normalize_body(raw_text)
    # strip() removes outer newlines; first line's leading spaces are also stripped
    assert result == "hello\n  world"


def test_normalize_body_empty_string() -> None:
    assert _normalize_body("") == ""


def test_normalize_body_whitespace_only() -> None:
    assert _normalize_body("   \n   \n   ") == ""


# -- build_work_package_body ---------------------------------------------------


def test_build_work_package_body_returns_template() -> None:
    body = build_work_package_body()
    assert "## Objective" in body
    assert "## Acceptance criteria" in body
    assert "## TDD Requirements" in body


def test_build_work_package_body_stable_across_calls() -> None:
    assert build_work_package_body() == build_work_package_body()


# -- refactor_open_issues ------------------------------------------------------


def _make_issue(number: Any, body: str | None = "old body") -> dict[str, Any]:
    return {"number": number, "body": body}


def test_refactor_dry_run_identifies_issues_needing_update(monkeypatch: pytest.MonkeyPatch) -> None:
    issues = [_make_issue(1, "stale body"), _make_issue(2, "other body")]
    monkeypatch.setattr(f"{_MODULE}.list_issues", lambda **_kwargs: issues)
    upsert_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(f"{_MODULE}.upsert_issue", lambda **kwargs: upsert_calls.append(kwargs))

    result = refactor_open_issues(runner=_RUNNER, repo=_REPO, apply=False)

    assert result["repo"] == _REPO
    assert result["apply"] is False
    assert result["total_open_issues"] == 2
    assert result["updated_count"] == 2
    assert result["updated_numbers"] == [1, 2]
    assert upsert_calls == [], "dry-run must not call upsert_issue"


def test_refactor_apply_calls_upsert_for_each_changed_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    issues = [_make_issue(10, "needs update"), _make_issue(20, "also needs update")]
    monkeypatch.setattr(f"{_MODULE}.list_issues", lambda **_kwargs: issues)
    upserted_numbers: list[int] = []
    monkeypatch.setattr(f"{_MODULE}.upsert_issue", lambda **kwargs: upserted_numbers.append(kwargs["number"]))

    result = refactor_open_issues(runner=_RUNNER, repo=_REPO, apply=True)

    assert result["apply"] is True
    assert result["updated_count"] == 2
    assert upserted_numbers == [10, 20]


def test_refactor_skips_non_int_issue_number(monkeypatch: pytest.MonkeyPatch) -> None:
    issues = [_make_issue("not-an-int", "body"), _make_issue(None, "body")]
    monkeypatch.setattr(f"{_MODULE}.list_issues", lambda **_kwargs: issues)
    monkeypatch.setattr(f"{_MODULE}.upsert_issue", lambda **kwargs: None)

    result = refactor_open_issues(runner=_RUNNER, repo=_REPO, apply=True)

    assert result["total_open_issues"] == 2
    assert result["updated_count"] == 0
    assert result["updated_numbers"] == []


def test_refactor_treats_none_body_as_empty_string(monkeypatch: pytest.MonkeyPatch) -> None:
    issues = [_make_issue(5, None)]
    monkeypatch.setattr(f"{_MODULE}.list_issues", lambda **_kwargs: issues)
    upserted_numbers: list[int] = []
    monkeypatch.setattr(f"{_MODULE}.upsert_issue", lambda **kwargs: upserted_numbers.append(kwargs["number"]))

    result = refactor_open_issues(runner=_RUNNER, repo=_REPO, apply=True)

    assert result["updated_count"] == 1
    assert upserted_numbers == [5]


def test_refactor_skips_issue_already_matching_template(monkeypatch: pytest.MonkeyPatch) -> None:
    template_body = build_work_package_body()
    issues = [_make_issue(7, template_body)]
    monkeypatch.setattr(f"{_MODULE}.list_issues", lambda **_kwargs: issues)
    upsert_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(f"{_MODULE}.upsert_issue", lambda **kwargs: upsert_calls.append(kwargs))

    result = refactor_open_issues(runner=_RUNNER, repo=_REPO, apply=True)

    assert result["updated_count"] == 0
    assert result["updated_numbers"] == []
    assert upsert_calls == []


def test_refactor_skips_body_matching_after_normalization(monkeypatch: pytest.MonkeyPatch) -> None:
    template_body = build_work_package_body()
    body_with_trailing_spaces = template_body.replace("\n", "   \n") + "   \n"
    issues = [_make_issue(8, body_with_trailing_spaces)]
    monkeypatch.setattr(f"{_MODULE}.list_issues", lambda **_kwargs: issues)
    monkeypatch.setattr(f"{_MODULE}.upsert_issue", lambda **kwargs: None)

    result = refactor_open_issues(runner=_RUNNER, repo=_REPO, apply=True)

    assert result["updated_count"] == 0


def test_refactor_returns_sorted_updated_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    issues = [_make_issue(30, "x"), _make_issue(10, "y"), _make_issue(20, "z")]
    monkeypatch.setattr(f"{_MODULE}.list_issues", lambda **_kwargs: issues)
    monkeypatch.setattr(f"{_MODULE}.upsert_issue", lambda **kwargs: None)

    result = refactor_open_issues(runner=_RUNNER, repo=_REPO, apply=True)

    assert result["updated_numbers"] == [10, 20, 30]


def test_refactor_no_open_issues(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(f"{_MODULE}.list_issues", lambda **_kwargs: [])
    monkeypatch.setattr(f"{_MODULE}.upsert_issue", lambda **kwargs: None)

    result = refactor_open_issues(runner=_RUNNER, repo=_REPO)

    assert result["total_open_issues"] == 0
    assert result["updated_count"] == 0


# -- _build_parser / _parse_args -----------------------------------------------


def test_build_parser_returns_argument_parser() -> None:
    parser = _build_parser()
    assert isinstance(parser, argparse.ArgumentParser)


def test_build_parser_defaults() -> None:
    parser = _build_parser()
    parsed = parser.parse_args([])
    assert parsed.repo is None
    assert parsed.apply is False


def test_build_parser_with_repo_and_apply() -> None:
    parser = _build_parser()
    parsed = parser.parse_args(["--repo", "owner/name", "--apply"])
    assert parsed.repo == "owner/name"
    assert parsed.apply is True


def test_parse_args_delegates_to_build_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["prog", "--repo", "a/b"])
    result = _parse_args()
    assert result.repo == "a/b"
    assert result.apply is False


# -- main ----------------------------------------------------------------------


def test_main_success_prints_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    fake_result = {
        "repo": _REPO,
        "apply": False,
        "total_open_issues": 1,
        "updated_count": 1,
        "updated_numbers": [1],
    }

    class FakeRunner:
        pass

    monkeypatch.setattr("sys.argv", ["prog", "--repo", _REPO])
    monkeypatch.setattr(f"{_MODULE}.SubprocessGhRunner", FakeRunner)
    monkeypatch.setattr(f"{_MODULE}.refactor_open_issues", lambda **_kwargs: fake_result)

    exit_code = main()

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["updated_count"] == 1


def test_main_uses_current_repo_when_no_repo_arg(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_result = {
        "repo": "detected/repo",
        "apply": False,
        "total_open_issues": 0,
        "updated_count": 0,
        "updated_numbers": [],
    }

    class FakeRunner:
        pass

    monkeypatch.setattr("sys.argv", ["prog"])
    monkeypatch.setattr(f"{_MODULE}.SubprocessGhRunner", FakeRunner)
    monkeypatch.setattr(f"{_MODULE}.current_repo", lambda _runner: "detected/repo")
    monkeypatch.setattr(f"{_MODULE}.refactor_open_issues", lambda **_kwargs: fake_result)

    exit_code = main()

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["repo"] == "detected/repo"


def test_main_returns_2_on_gh_cli_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeRunner:
        pass

    def raise_gh_cli_error(**_kwargs: Any) -> None:
        raise GhCliError("fail", argv=["gh"], returncode=1, stdout="", stderr="fail")

    monkeypatch.setattr("sys.argv", ["prog", "--repo", _REPO])
    monkeypatch.setattr(f"{_MODULE}.SubprocessGhRunner", FakeRunner)
    monkeypatch.setattr(f"{_MODULE}.refactor_open_issues", raise_gh_cli_error)

    exit_code = main()

    assert exit_code == 2


def test_main_returns_2_on_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeRunner:
        pass

    def raise_value_error(**_kwargs: Any) -> None:
        msg = "bad input"
        raise ValueError(msg)

    monkeypatch.setattr("sys.argv", ["prog", "--repo", _REPO])
    monkeypatch.setattr(f"{_MODULE}.SubprocessGhRunner", FakeRunner)
    monkeypatch.setattr(f"{_MODULE}.refactor_open_issues", raise_value_error)

    exit_code = main()

    assert exit_code == 2
