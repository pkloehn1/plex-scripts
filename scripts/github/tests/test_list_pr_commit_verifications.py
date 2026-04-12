"""Tests for list_pr_commit_verifications module."""

from __future__ import annotations

import argparse
import json
from typing import Any

import pytest

from scripts.github.conftest import ExpectedCall, QueueRunner
from scripts.github.gh_cli import GhCliError, GhResult
from scripts.github.list_pr_commit_verifications import (
    _build_parser,
    _parse_args,
    _parse_fail_reasons,
    _should_fail,
    filter_commits,
    list_pr_commit_verifications,
    main,
    summarize_reasons,
)

_COMMITS_ARGV = ["gh", "api", "--paginate", "/repos/o/n/pulls/42/commits"]


def _sample_raw_commit(
    *,
    sha: str = "abc123",
    message: str = "fix: something\n\ndetails",
    verified: bool = True,
    reason: str = "valid",
) -> dict:
    return {
        "sha": sha,
        "html_url": f"https://github.com/o/n/commit/{sha}",
        "commit": {
            "message": message,
            "verification": {
                "verified": verified,
                "reason": reason,
                "signature": "sig-data",
                "payload": "payload-data",
                "verified_at": None,
            },
            "author": {"name": "Alice", "email": "a@b.com"},
            "committer": {"name": "Alice", "email": "a@b.com"},
        },
    }


# -- list_pr_commit_verifications ---------------------------------------------


def test_normal_commits() -> None:
    raw_payload = [
        _sample_raw_commit(sha="aaa", message="first commit"),
        _sample_raw_commit(sha="bbb", message="second\nwith body", verified=False, reason="unsigned"),
    ]
    runner = QueueRunner([ExpectedCall(argv=_COMMITS_ARGV, stdout=json.dumps(raw_payload))])
    result = list_pr_commit_verifications(runner=runner, repo="o/n", pr=42)

    assert len(result) == 2
    assert result[0]["sha"] == "aaa"
    assert result[0]["subject"] == "first commit"
    assert result[0]["verified"] is True
    assert result[0]["reason"] == "valid"
    assert result[0]["author"] == {"name": "Alice", "email": "a@b.com"}

    assert result[1]["sha"] == "bbb"
    assert result[1]["subject"] == "second"
    assert result[1]["verified"] is False
    assert result[1]["reason"] == "unsigned"
    runner.assert_exhausted()


def test_raises_on_non_list_payload() -> None:
    runner = QueueRunner([ExpectedCall(argv=_COMMITS_ARGV, stdout='{"unexpected": true}')])
    with pytest.raises(ValueError, match="Unexpected commits payload"):
        list_pr_commit_verifications(runner=runner, repo="o/n", pr=42)


def test_skips_non_dict_items() -> None:
    raw_payload = [_sample_raw_commit(), "not-a-dict", 42, None]
    runner = QueueRunner([ExpectedCall(argv=_COMMITS_ARGV, stdout=json.dumps(raw_payload))])
    result = list_pr_commit_verifications(runner=runner, repo="o/n", pr=42)
    assert len(result) == 1


def test_missing_commit_object() -> None:
    raw_payload = [{"sha": "nocommit", "html_url": "https://example.com"}]
    runner = QueueRunner([ExpectedCall(argv=_COMMITS_ARGV, stdout=json.dumps(raw_payload))])
    result = list_pr_commit_verifications(runner=runner, repo="o/n", pr=42)

    assert len(result) == 1
    assert result[0]["sha"] == "nocommit"
    assert result[0]["subject"] == ""
    assert result[0]["verified"] is None
    assert result[0]["reason"] is None
    assert result[0]["author"] is None


def test_missing_verification_object() -> None:
    raw_payload = [
        {
            "sha": "noverify",
            "html_url": "https://example.com",
            "commit": {
                "message": "msg here",
                "author": {"name": "Bob", "email": "b@c.com"},
                "committer": {"name": "Bob", "email": "b@c.com"},
            },
        }
    ]
    runner = QueueRunner([ExpectedCall(argv=_COMMITS_ARGV, stdout=json.dumps(raw_payload))])
    result = list_pr_commit_verifications(runner=runner, repo="o/n", pr=42)

    assert result[0]["subject"] == "msg here"
    assert result[0]["verified"] is None
    assert result[0]["signature"] is None


def test_empty_message() -> None:
    raw_payload = [{"sha": "emptymsg", "html_url": "https://example.com", "commit": {"message": ""}}]
    runner = QueueRunner([ExpectedCall(argv=_COMMITS_ARGV, stdout=json.dumps(raw_payload))])
    result = list_pr_commit_verifications(runner=runner, repo="o/n", pr=42)
    assert result[0]["subject"] == ""


def test_non_string_message() -> None:
    raw_payload = [{"sha": "badmsg", "html_url": "https://example.com", "commit": {"message": 12345}}]
    runner = QueueRunner([ExpectedCall(argv=_COMMITS_ARGV, stdout=json.dumps(raw_payload))])
    result = list_pr_commit_verifications(runner=runner, repo="o/n", pr=42)
    assert result[0]["subject"] == ""


# -- summarize_reasons ---------------------------------------------------------


def test_summarize_multiple_reasons() -> None:
    commits = [
        {"reason": "valid"},
        {"reason": "valid"},
        {"reason": "unsigned"},
    ]
    result = summarize_reasons(commits)
    assert result == {"valid": 2, "unsigned": 1}


def test_summarize_unknown_for_non_string_reason() -> None:
    commits: list[dict[str, Any]] = [{"reason": None}, {"reason": 42}]
    result = summarize_reasons(commits)
    assert result == {"unknown": 2}


def test_summarize_unknown_for_empty_reason() -> None:
    commits = [{"reason": ""}]
    result = summarize_reasons(commits)
    assert result == {"unknown": 1}


def test_summarize_sort_by_count_then_name() -> None:
    commits = [
        {"reason": "unsigned"},
        {"reason": "no_user"},
        {"reason": "unsigned"},
        {"reason": "no_user"},
        {"reason": "valid"},
    ]
    result = summarize_reasons(commits)
    keys = list(result.keys())
    assert keys == ["no_user", "unsigned", "valid"]
    assert result["no_user"] == 2
    assert result["unsigned"] == 2
    assert result["valid"] == 1


# -- filter_commits ------------------------------------------------------------


def test_filter_commits_returns_all_when_not_only_failing() -> None:
    commits = [{"verified": True}, {"verified": False}]
    result = filter_commits(commits, only_failing=False)
    assert result == commits


def test_filter_commits_excludes_verified_true() -> None:
    commits: list[dict[str, Any]] = [
        {"verified": True, "sha": "pass"},
        {"verified": False, "sha": "fail"},
        {"verified": None, "sha": "none"},
    ]
    result = filter_commits(commits, only_failing=True)
    assert len(result) == 2
    assert all(entry["sha"] != "pass" for entry in result)


# -- _parse_fail_reasons -------------------------------------------------------


def test_parse_fail_reasons_none() -> None:
    assert _parse_fail_reasons(None) == set()


def test_parse_fail_reasons_empty_string() -> None:
    assert _parse_fail_reasons("") == set()


def test_parse_fail_reasons_csv() -> None:
    assert _parse_fail_reasons("unsigned,no_user") == {"unsigned", "no_user"}


def test_parse_fail_reasons_whitespace_handling() -> None:
    assert _parse_fail_reasons("  unsigned , no_user  , ") == {"unsigned", "no_user"}


# -- _should_fail --------------------------------------------------------------


def test_should_fail_empty_reasons_returns_false() -> None:
    commits = [{"reason": "unsigned"}]
    assert _should_fail(commits, set()) is False


def test_should_fail_matching_reason_returns_true() -> None:
    commits = [{"reason": "valid"}, {"reason": "unsigned"}]
    assert _should_fail(commits, {"unsigned"}) is True


def test_should_fail_no_match_returns_false() -> None:
    commits = [{"reason": "valid"}]
    assert _should_fail(commits, {"unsigned"}) is False


def test_should_fail_non_string_reason_skipped() -> None:
    commits: list[dict[str, Any]] = [{"reason": None}, {"reason": 42}]
    assert _should_fail(commits, {"None", "42"}) is False


# -- _build_parser / _parse_args -----------------------------------------------


def test_build_parser_returns_argument_parser() -> None:
    parser = _build_parser()
    assert isinstance(parser, argparse.ArgumentParser)


def test_build_parser_defaults() -> None:
    parser = _build_parser()
    args = parser.parse_args([])
    assert args.repo is None
    assert args.pr is None
    assert args.only_failing is False
    assert args.fail_on is None


def test_build_parser_all_flags() -> None:
    parser = _build_parser()
    args = parser.parse_args(["--repo", "o/n", "--pr", "42", "--only-failing", "--fail-on", "unsigned"])
    assert args.repo == "o/n"
    assert args.pr == 42
    assert args.only_failing is True
    assert args.fail_on == "unsigned"


def test_parse_args_thin_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["prog"])
    namespace = _parse_args()
    assert namespace.repo is None
    assert namespace.only_failing is False


# -- main ----------------------------------------------------------------------


def test_main_success(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    raw_payload = [_sample_raw_commit(sha="aaa", verified=True, reason="valid")]

    class _FakeRunner:
        def run(self, argv: list[str], *, input_text: str | None = None) -> GhResult:
            return GhResult(stdout=json.dumps(raw_payload), stderr="")

    monkeypatch.setattr("scripts.github.list_pr_commit_verifications.SubprocessGhRunner", _FakeRunner)
    monkeypatch.setattr("sys.argv", ["prog", "--repo", "o/n", "--pr", "42"])

    exit_code = main()
    assert exit_code == 0

    parsed = json.loads(capsys.readouterr().out)
    assert parsed["repo"] == "o/n"
    assert parsed["pr"] == 42
    assert parsed["count"] == 1
    assert parsed["commits"][0]["sha"] == "aaa"


def test_main_fail_on_triggers_exit_2(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    raw_payload = [_sample_raw_commit(sha="bad", verified=False, reason="unsigned")]

    class _FakeRunner:
        def run(self, argv: list[str], *, input_text: str | None = None) -> GhResult:
            return GhResult(stdout=json.dumps(raw_payload), stderr="")

    monkeypatch.setattr("scripts.github.list_pr_commit_verifications.SubprocessGhRunner", _FakeRunner)
    monkeypatch.setattr("sys.argv", ["prog", "--repo", "o/n", "--pr", "42", "--fail-on", "unsigned"])

    exit_code = main()
    assert exit_code == 2

    parsed = json.loads(capsys.readouterr().out)
    assert parsed["count"] == 1


def test_main_only_failing_filters_output(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    raw_payload = [
        _sample_raw_commit(sha="good", verified=True, reason="valid"),
        _sample_raw_commit(sha="bad", verified=False, reason="unsigned"),
    ]

    class _FakeRunner:
        def run(self, argv: list[str], *, input_text: str | None = None) -> GhResult:
            return GhResult(stdout=json.dumps(raw_payload), stderr="")

    monkeypatch.setattr("scripts.github.list_pr_commit_verifications.SubprocessGhRunner", _FakeRunner)
    monkeypatch.setattr("sys.argv", ["prog", "--repo", "o/n", "--pr", "42", "--only-failing"])

    exit_code = main()
    assert exit_code == 0

    parsed = json.loads(capsys.readouterr().out)
    assert parsed["count"] == 2
    assert len(parsed["commits"]) == 1
    assert parsed["commits"][0]["sha"] == "bad"


def test_main_gh_cli_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _ErrorRunner:
        def run(self, argv: list[str], *, input_text: str | None = None) -> GhResult:
            raise GhCliError("fail", argv=argv, returncode=1, stdout="", stderr="oops")

    monkeypatch.setattr("scripts.github.list_pr_commit_verifications.SubprocessGhRunner", _ErrorRunner)
    monkeypatch.setattr("sys.argv", ["prog", "--repo", "o/n", "--pr", "42"])

    assert main() == 2


def test_main_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BadRunner:
        def run(self, argv: list[str], *, input_text: str | None = None) -> GhResult:
            return GhResult(stdout='{"not": "a list"}', stderr="")

    monkeypatch.setattr("scripts.github.list_pr_commit_verifications.SubprocessGhRunner", _BadRunner)
    monkeypatch.setattr("sys.argv", ["prog", "--repo", "o/n", "--pr", "42"])

    assert main() == 2
