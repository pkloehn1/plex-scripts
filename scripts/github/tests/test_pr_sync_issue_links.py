"""Tests for pr_sync_issue_links module."""

from __future__ import annotations

import argparse
import json

import pytest

from scripts.github.conftest import ExpectedCall, QueueRunner
from scripts.github.pr_sync_issue_links import (
    SyncResult,
    _build_parser,
    _extract_issue_links,
    _fetch_pr,
    _fetch_pr_body,
    _normalize_newlines,
    _parse_args,
    _parse_positive_int,
    _print_human_summary,
    _refresh_auto_summary,
    _run,
    _strip_issue_link_lines,
    _try_parse_close_line,
    _try_parse_issue_num_token,
    _try_parse_relate_line,
    _update_pr_body,
    main,
    sync_issue_links_in_body,
    sync_pr_issue_links,
)

_REPO = "octo/widgets"
_PR_NUMBER = 42
_FETCH_ARGV = ["gh", "api", f"/repos/octo/widgets/pulls/{_PR_NUMBER}"]


def _patch_argv(body: str | None = "") -> ExpectedCall:
    return ExpectedCall(
        argv=[
            "gh",
            "api",
            "--method",
            "PATCH",
            f"/repos/octo/widgets/pulls/{_PR_NUMBER}",
            "-f",
            f"body={body}",
        ],
        stdout=json.dumps({"body": body}),
    )


def _fetch_call(body: str | None = "") -> ExpectedCall:
    return ExpectedCall(
        argv=_FETCH_ARGV,
        stdout=json.dumps({"body": body}),
    )


# -- _parse_positive_int -------------------------------------------------------


class TestParsePositiveInt:
    def test_valid_integer(self) -> None:
        assert _parse_positive_int("7") == 7

    def test_non_integer_raises(self) -> None:
        with pytest.raises(ValueError, match="must be an integer"):
            _parse_positive_int("abc")

    def test_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            _parse_positive_int("0")

    def test_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            _parse_positive_int("-3")


# -- _try_parse_issue_num_token ------------------------------------------------


class TestTryParseIssueNumToken:
    def test_valid_hash_number(self) -> None:
        assert _try_parse_issue_num_token("#42") == 42

    def test_no_hash_prefix(self) -> None:
        assert _try_parse_issue_num_token("42") is None

    def test_non_digit_after_hash(self) -> None:
        assert _try_parse_issue_num_token("#abc") is None

    def test_zero_returns_none(self) -> None:
        assert _try_parse_issue_num_token("#0") is None


# -- _try_parse_close_line / _try_parse_relate_line ----------------------------


class TestTryParseCloseLine:
    def test_match(self) -> None:
        assert _try_parse_close_line("Closes #10") == 10

    def test_no_match_wrong_keyword(self) -> None:
        assert _try_parse_close_line("Fixes #10") is None

    def test_no_match_extra_tokens(self) -> None:
        assert _try_parse_close_line("Closes #10 extra") is None


class TestTryParseRelateLine:
    def test_match(self) -> None:
        assert _try_parse_relate_line("Relates to #5") == 5

    def test_no_match_wrong_keyword(self) -> None:
        assert _try_parse_relate_line("Related to #5") is None

    def test_no_match_missing_to(self) -> None:
        assert _try_parse_relate_line("Relates #5") is None


# -- _strip_issue_link_lines ---------------------------------------------------


class TestStripIssueLinkLines:
    def test_removes_close_and_relate_lines(self) -> None:
        lines = ["Some text", "Closes #1", "Relates to #2", "Keep this"]
        result = _strip_issue_link_lines(lines)
        assert result == ["Some text", "Keep this"]

    def test_removes_linked_issue_prefix(self) -> None:
        lines = ["Linked Issue: something", "Keep"]
        result = _strip_issue_link_lines(lines)
        assert result == ["Keep"]

    def test_keeps_unrelated_lines(self) -> None:
        lines = ["Hello", "World"]
        assert _strip_issue_link_lines(lines) == ["Hello", "World"]


# -- _normalize_newlines -------------------------------------------------------


class TestNormalizeNewlines:
    def test_strips_carriage_return(self) -> None:
        assert _normalize_newlines("a\r\nb\r\n") == ["a", "b"]

    def test_plain_newlines(self) -> None:
        assert _normalize_newlines("x\ny") == ["x", "y"]


# -- _extract_issue_links ------------------------------------------------------


class TestExtractIssueLinks:
    def test_extracts_both_types(self) -> None:
        lines = ["Closes #1", "Relates to #2", "Closes #3", "Other"]
        closes, relates = _extract_issue_links(lines)
        assert closes == {1, 3}
        assert relates == {2}

    def test_empty_lines(self) -> None:
        closes, relates = _extract_issue_links([])
        assert closes == set()
        assert relates == set()


# -- sync_issue_links_in_body --------------------------------------------------


class TestSyncIssueLinksInBody:
    def test_adds_links_to_existing_body(self) -> None:
        result = sync_issue_links_in_body(body="Hello", closes={1}, relates={2})
        assert "Hello" in result
        assert "Closes #1" in result
        assert "Relates to #2" in result
        assert result.endswith("\n")

    def test_strips_old_links_and_adds_new(self) -> None:
        old_body = "Intro\nCloses #99\nRelates to #88"
        result = sync_issue_links_in_body(body=old_body, closes={1}, relates=set())
        assert "Closes #99" not in result
        assert "Relates to #88" not in result
        assert "Closes #1" in result

    def test_blank_body(self) -> None:
        result = sync_issue_links_in_body(body="", closes={5}, relates=set())
        assert "Closes #5" in result

    def test_none_body(self) -> None:
        result = sync_issue_links_in_body(body=None, closes={3}, relates={4})
        assert "Closes #3" in result
        assert "Relates to #4" in result

    def test_no_links_produces_trailing_newline(self) -> None:
        result = sync_issue_links_in_body(body="Hello", closes=set(), relates=set())
        assert result == "Hello\n"

    def test_sorted_output(self) -> None:
        result = sync_issue_links_in_body(body="", closes={3, 1}, relates={4, 2})
        lines = result.strip().splitlines()
        assert lines == ["Closes #1", "Closes #3", "Relates to #2", "Relates to #4"]

    def test_strips_leading_blank_lines_after_link_removal(self) -> None:
        # Body where the first line is an issue link followed by blank then content.
        # After stripping the link, the leading blank should be removed.
        body_with_leading_link = "Closes #99\n\nContent here"
        result = sync_issue_links_in_body(body=body_with_leading_link, closes={1}, relates=set())
        result_lines = result.strip().splitlines()
        assert result_lines[0] == "Content here"
        assert "Closes #1" in result


# -- _fetch_pr / _update_pr_body ----------------------------------------------


class TestFetchPr:
    def test_success(self) -> None:
        payload = {"body": "hello", "number": _PR_NUMBER}
        runner = QueueRunner([ExpectedCall(argv=_FETCH_ARGV, stdout=json.dumps(payload))])
        result = _fetch_pr(runner=runner, repo=_REPO, pr_number=_PR_NUMBER)
        assert result == payload
        runner.assert_exhausted()

    def test_non_dict_raises(self) -> None:
        runner = QueueRunner([ExpectedCall(argv=_FETCH_ARGV, stdout=json.dumps([1, 2]))])
        with pytest.raises(ValueError, match="Unexpected PR payload"):
            _fetch_pr(runner=runner, repo=_REPO, pr_number=_PR_NUMBER)


class TestUpdatePrBody:
    def test_success(self) -> None:
        new_body = "updated"
        patch_argv = [
            "gh",
            "api",
            "--method",
            "PATCH",
            f"/repos/octo/widgets/pulls/{_PR_NUMBER}",
            "-f",
            f"body={new_body}",
        ]
        payload = {"body": new_body}
        runner = QueueRunner([ExpectedCall(argv=patch_argv, stdout=json.dumps(payload))])
        result = _update_pr_body(runner=runner, repo=_REPO, pr_number=_PR_NUMBER, body=new_body)
        assert result == payload
        runner.assert_exhausted()

    def test_non_dict_raises(self) -> None:
        new_body = "updated"
        patch_argv = [
            "gh",
            "api",
            "--method",
            "PATCH",
            f"/repos/octo/widgets/pulls/{_PR_NUMBER}",
            "-f",
            f"body={new_body}",
        ]
        runner = QueueRunner([ExpectedCall(argv=patch_argv, stdout=json.dumps("string"))])
        with pytest.raises(ValueError, match="Unexpected PR payload"):
            _update_pr_body(runner=runner, repo=_REPO, pr_number=_PR_NUMBER, body=new_body)


# -- _fetch_pr_body ------------------------------------------------------------


class TestFetchPrBody:
    def test_returns_body_string(self) -> None:
        runner = QueueRunner([_fetch_call("Hello body")])
        assert _fetch_pr_body(runner=runner, repo=_REPO, pr_number=_PR_NUMBER) == "Hello body"
        runner.assert_exhausted()

    def test_none_body_returns_empty_string(self) -> None:
        runner = QueueRunner([ExpectedCall(argv=_FETCH_ARGV, stdout=json.dumps({"body": None}))])
        assert _fetch_pr_body(runner=runner, repo=_REPO, pr_number=_PR_NUMBER) == ""


# -- sync_pr_issue_links -------------------------------------------------------


class TestSyncPrIssueLinks:
    def test_changed_with_update(self) -> None:
        old_body = "Intro\n"
        new_body = sync_issue_links_in_body(body=old_body, closes={1}, relates=set())
        runner = QueueRunner(
            [
                _fetch_call(old_body),
                _patch_argv(new_body),
            ]
        )
        result = sync_pr_issue_links(
            runner=runner,
            repo=_REPO,
            pr_number=_PR_NUMBER,
            closes={1},
            relates=set(),
            dry_run=False,
            merge_existing=False,
        )
        assert result.changed is True
        assert result.closes == [1]
        runner.assert_exhausted()

    def test_not_changed(self) -> None:
        body = sync_issue_links_in_body(body="Intro", closes={1}, relates=set())
        runner = QueueRunner([_fetch_call(body)])
        result = sync_pr_issue_links(
            runner=runner,
            repo=_REPO,
            pr_number=_PR_NUMBER,
            closes={1},
            relates=set(),
            dry_run=False,
            merge_existing=False,
        )
        assert result.changed is False
        runner.assert_exhausted()

    def test_dry_run_no_patch(self) -> None:
        old_body = "Intro\n"
        runner = QueueRunner([_fetch_call(old_body)])
        result = sync_pr_issue_links(
            runner=runner,
            repo=_REPO,
            pr_number=_PR_NUMBER,
            closes={1},
            relates=set(),
            dry_run=True,
            merge_existing=False,
        )
        assert result.changed is True
        runner.assert_exhausted()

    def test_merge_existing(self) -> None:
        old_body = "Intro\n\nCloses #5\nRelates to #6\n"
        new_body = sync_issue_links_in_body(body=old_body, closes={1, 5}, relates={6})
        runner = QueueRunner(
            [
                _fetch_call(old_body),
                _patch_argv(new_body),
            ]
        )
        result = sync_pr_issue_links(
            runner=runner,
            repo=_REPO,
            pr_number=_PR_NUMBER,
            closes={1},
            relates=set(),
            dry_run=False,
            merge_existing=True,
        )
        assert result.changed is True
        assert 5 in result.closes
        assert 1 in result.closes
        assert 6 in result.relates
        runner.assert_exhausted()


# -- _build_parser -------------------------------------------------------------


class TestBuildParser:
    def test_returns_parser(self) -> None:
        assert isinstance(_build_parser(), argparse.ArgumentParser)


class TestParseArgs:
    def test_returns_namespace(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "sys.argv",
            ["prog", "--repo", "octo/widgets", "--pr", "42", "--close", "1"],
        )
        namespace = _parse_args()
        assert isinstance(namespace, argparse.Namespace)
        assert namespace.repo == "octo/widgets"
        assert namespace.pr == 42
        assert namespace.close == ["1"]


# -- _refresh_auto_summary -----------------------------------------------------


class TestRefreshAutoSummary:
    def test_dry_run_skips_patch(self, monkeypatch) -> None:
        fetch_runner = QueueRunner([_fetch_call("old body")])

        def fake_refresh(*, existing_body, git_runner, base_branch):
            return "new body"

        monkeypatch.setattr(
            "scripts.github.pr_auto_summary.refresh_auto_summary_in_body",
            fake_refresh,
        )
        monkeypatch.setattr(
            "scripts.common.git_runner.run_git",
            lambda *args, **kwargs: None,
        )

        _refresh_auto_summary(
            gh_runner=fetch_runner,
            repo=_REPO,
            pr_number=_PR_NUMBER,
            base_branch="main",
            dry_run=True,
        )
        fetch_runner.assert_exhausted()

    def test_updated_body_triggers_patch(self, monkeypatch) -> None:
        updated_body = "new body"
        runner = QueueRunner(
            [
                _fetch_call("old body"),
                _patch_argv(updated_body),
            ]
        )

        def fake_refresh(*, existing_body, git_runner, base_branch):
            return updated_body

        monkeypatch.setattr(
            "scripts.github.pr_auto_summary.refresh_auto_summary_in_body",
            fake_refresh,
        )
        monkeypatch.setattr(
            "scripts.common.git_runner.run_git",
            lambda *args, **kwargs: None,
        )

        _refresh_auto_summary(
            gh_runner=runner,
            repo=_REPO,
            pr_number=_PR_NUMBER,
            base_branch="main",
            dry_run=False,
        )
        runner.assert_exhausted()

    def test_unchanged_body_no_patch(self, monkeypatch) -> None:
        same_body = "same body"
        runner = QueueRunner([_fetch_call(same_body)])

        def fake_refresh(*, existing_body, git_runner, base_branch):
            return same_body

        monkeypatch.setattr(
            "scripts.github.pr_auto_summary.refresh_auto_summary_in_body",
            fake_refresh,
        )
        monkeypatch.setattr(
            "scripts.common.git_runner.run_git",
            lambda *args, **kwargs: None,
        )

        _refresh_auto_summary(
            gh_runner=runner,
            repo=_REPO,
            pr_number=_PR_NUMBER,
            base_branch=None,
            dry_run=False,
        )
        runner.assert_exhausted()

    def test_default_git_runner_delegates_to_run_git(self, monkeypatch) -> None:
        """Verify _DefaultGitRunner.run_git calls the module-level run_git."""
        from pathlib import Path

        captured_calls: list[tuple] = []

        def tracking_run_git(git_args, *, cwd=None):
            captured_calls.append((git_args, cwd))
            from scripts.common.git_runner import GitResult

            return GitResult(stdout="", stderr="", returncode=0)

        monkeypatch.setattr(
            "scripts.common.git_runner.run_git",
            tracking_run_git,
        )

        fetch_runner = QueueRunner([_fetch_call("body")])

        def fake_refresh(*, existing_body, git_runner, base_branch):
            # Exercise the _DefaultGitRunner.run_git path (line 290)
            git_runner.run_git(["log", "--oneline"], cwd=Path("."))
            return existing_body

        monkeypatch.setattr(
            "scripts.github.pr_auto_summary.refresh_auto_summary_in_body",
            fake_refresh,
        )

        _refresh_auto_summary(
            gh_runner=fetch_runner,
            repo=_REPO,
            pr_number=_PR_NUMBER,
            base_branch="main",
            dry_run=False,
        )
        fetch_runner.assert_exhausted()
        assert len(captured_calls) == 1
        assert captured_calls[0][0] == ["log", "--oneline"]


# -- _run ----------------------------------------------------------------------


class TestRun:
    def _make_args(self, **overrides) -> argparse.Namespace:
        defaults = {
            "repo": _REPO,
            "pr": _PR_NUMBER,
            "close": None,
            "relate": None,
            "dry_run": False,
            "merge_existing": False,
            "json": False,
            "auto_summary": False,
            "base_branch": None,
        }
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_json_output(self, capsys) -> None:
        body = sync_issue_links_in_body(body="", closes={1}, relates=set())
        runner = QueueRunner(
            [
                _fetch_call(""),
                _patch_argv(body),
            ]
        )
        args = self._make_args(close=["1"], json=True)
        assert _run(args, _build_parser(), runner) == 0
        output = json.loads(capsys.readouterr().out)
        assert output["changed"] is True
        assert output["closes"] == [1]
        runner.assert_exhausted()

    def test_text_output(self, capsys) -> None:
        body = sync_issue_links_in_body(body="", closes={1}, relates=set())
        runner = QueueRunner(
            [
                _fetch_call(""),
                _patch_argv(body),
            ]
        )
        args = self._make_args(close=["1"])
        assert _run(args, _build_parser(), runner) == 0
        captured = capsys.readouterr().out
        assert "Updated" in captured
        runner.assert_exhausted()

    def test_auto_summary_path(self, monkeypatch, capsys) -> None:
        old_body = "Intro\n"
        new_body = sync_issue_links_in_body(body=old_body, closes={1}, relates=set())

        # sync call (fetch + patch) then auto-summary call (fetch only, no change)
        runner = QueueRunner(
            [
                _fetch_call(old_body),
                _patch_argv(new_body),
                _fetch_call(new_body),
            ]
        )

        def fake_refresh(*, existing_body, git_runner, base_branch):
            return existing_body  # no change

        monkeypatch.setattr(
            "scripts.github.pr_auto_summary.refresh_auto_summary_in_body",
            fake_refresh,
        )
        monkeypatch.setattr(
            "scripts.common.git_runner.run_git",
            lambda *args, **kwargs: None,
        )

        args = self._make_args(close=["1"], auto_summary=True, base_branch="main")
        assert _run(args, _build_parser(), runner) == 0
        runner.assert_exhausted()

    def test_no_close_no_relate(self, capsys) -> None:
        body = sync_issue_links_in_body(body="Intro", closes=set(), relates=set())
        runner = QueueRunner([_fetch_call(body)])
        args = self._make_args()
        assert _run(args, _build_parser(), runner) == 0
        captured = capsys.readouterr().out
        assert "No changes" in captured
        runner.assert_exhausted()


# -- main ----------------------------------------------------------------------


class TestMain:
    def test_delegates(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "scripts.github.pr_sync_issue_links.run_actionable_main",
            lambda **kwargs: 0,
        )
        assert main() == 0


# -- _print_human_summary ------------------------------------------------------


class TestPrintHumanSummary:
    def test_no_change(self, capsys) -> None:
        result = SyncResult(repo=_REPO, pr=_PR_NUMBER, closes=[], relates=[], changed=False)
        _print_human_summary(result=result, dry_run=False)
        captured = capsys.readouterr().out
        assert "No changes" in captured

    def test_changed_not_dry_run(self, capsys) -> None:
        result = SyncResult(repo=_REPO, pr=_PR_NUMBER, closes=[1], relates=[], changed=True)
        _print_human_summary(result=result, dry_run=False)
        captured = capsys.readouterr().out
        assert "Updated" in captured

    def test_changed_dry_run(self, capsys) -> None:
        result = SyncResult(repo=_REPO, pr=_PR_NUMBER, closes=[1], relates=[], changed=True)
        _print_human_summary(result=result, dry_run=True)
        captured = capsys.readouterr().out
        assert "Would update" in captured
