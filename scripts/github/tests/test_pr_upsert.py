"""Tests for pr_upsert module."""

from __future__ import annotations

import argparse
import json
from typing import Any
from unittest.mock import patch

import pytest

from scripts.github.conftest import make_call, make_runner
from scripts.github.pr_upsert import (
    _build_parser,
    _fetch_pr,
    _mark_pr_ready_for_review,
    _parse_args,
    _pr_method_endpoint,
    _resolve_auto_summary_body,
    _run,
    main,
    upsert_pr,
)

_REPO = "o/n"


# -- _pr_method_endpoint -------------------------------------------------------


def test_pr_method_endpoint_create_returns_post() -> None:
    method, endpoint = _pr_method_endpoint(
        owner="o",
        name="n",
        number=None,
        title="My PR",
        base="main",
        head="feature",
    )
    assert method == "POST"
    assert endpoint == "/repos/o/n/pulls"


def test_pr_method_endpoint_edit_returns_patch() -> None:
    method, endpoint = _pr_method_endpoint(
        owner="o",
        name="n",
        number=10,
        title=None,
        base=None,
        head=None,
    )
    assert method == "PATCH"
    assert endpoint == "/repos/o/n/pulls/10"


def test_pr_method_endpoint_create_requires_title() -> None:
    with pytest.raises(ValueError, match="title is required"):
        _pr_method_endpoint(
            owner="o",
            name="n",
            number=None,
            title=None,
            base="main",
            head="feature",
        )


def test_pr_method_endpoint_create_requires_base() -> None:
    with pytest.raises(ValueError, match="base is required"):
        _pr_method_endpoint(
            owner="o",
            name="n",
            number=None,
            title="PR",
            base=None,
            head="feature",
        )


def test_pr_method_endpoint_create_requires_head() -> None:
    with pytest.raises(ValueError, match="head is required"):
        _pr_method_endpoint(
            owner="o",
            name="n",
            number=None,
            title="PR",
            base="main",
            head=None,
        )


def test_pr_method_endpoint_create_rejects_empty_title() -> None:
    with pytest.raises(ValueError, match="title is required"):
        _pr_method_endpoint(
            owner="o",
            name="n",
            number=None,
            title="   ",
            base="main",
            head="feature",
        )


def test_pr_method_endpoint_create_rejects_empty_base() -> None:
    with pytest.raises(ValueError, match="base is required"):
        _pr_method_endpoint(
            owner="o",
            name="n",
            number=None,
            title="PR",
            base="   ",
            head="feature",
        )


def test_pr_method_endpoint_create_rejects_empty_head() -> None:
    with pytest.raises(ValueError, match="head is required"):
        _pr_method_endpoint(
            owner="o",
            name="n",
            number=None,
            title="PR",
            base="main",
            head="   ",
        )


def test_pr_method_endpoint_edit_rejects_zero() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        _pr_method_endpoint(
            owner="o",
            name="n",
            number=0,
            title=None,
            base=None,
            head=None,
        )


def test_pr_method_endpoint_edit_rejects_negative() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        _pr_method_endpoint(
            owner="o",
            name="n",
            number=-1,
            title=None,
            base=None,
            head=None,
        )


# -- _fetch_pr -----------------------------------------------------------------


def test_fetch_pr_returns_dict() -> None:
    pr_payload = {"number": 5, "html_url": "https://github.com/o/n/pull/5"}
    runner = make_runner(
        make_call(
            ["gh", "api", "/repos/o/n/pulls/5"],
            pr_payload,
        )
    )
    result = _fetch_pr(runner=runner, repo=_REPO, number=5)
    assert result == pr_payload
    runner.assert_exhausted()


def test_fetch_pr_raises_on_non_dict() -> None:
    runner = make_runner(make_call(["gh", "api", "/repos/o/n/pulls/5"], [1, 2, 3]))
    with pytest.raises(ValueError, match="Unexpected PR payload"):
        _fetch_pr(runner=runner, repo=_REPO, number=5)


# -- _mark_pr_ready_for_review ------------------------------------------------


def test_mark_pr_ready_for_review_draft_pr() -> None:
    draft_pr = {"draft": True, "number": 7}
    ready_response: dict[str, Any] = {}
    runner = make_runner(
        make_call(["gh", "api", "/repos/o/n/pulls/7"], draft_pr),
        make_call(
            ["gh", "api", "--method", "POST", "/repos/o/n/pulls/7/ready_for_review"],
            ready_response,
        ),
    )
    _mark_pr_ready_for_review(runner=runner, repo=_REPO, number=7)
    runner.assert_exhausted()


def test_mark_pr_ready_for_review_non_draft_skips() -> None:
    non_draft_pr = {"draft": False, "number": 7}
    runner = make_runner(
        make_call(["gh", "api", "/repos/o/n/pulls/7"], non_draft_pr),
    )
    _mark_pr_ready_for_review(runner=runner, repo=_REPO, number=7)
    runner.assert_exhausted()


def test_mark_pr_ready_for_review_missing_draft_key_skips() -> None:
    no_draft_key = {"number": 7}
    runner = make_runner(
        make_call(["gh", "api", "/repos/o/n/pulls/7"], no_draft_key),
    )
    _mark_pr_ready_for_review(runner=runner, repo=_REPO, number=7)
    runner.assert_exhausted()


# -- upsert_pr ----------------------------------------------------------------


def test_upsert_pr_create_with_all_fields() -> None:
    pr_response = {"number": 1, "html_url": "https://github.com/o/n/pull/1"}
    runner = make_runner(
        make_call(
            [
                "gh",
                "api",
                "--method",
                "POST",
                "/repos/o/n/pulls",
                "-f",
                "title=New PR",
                "-f",
                "body=Body text",
                "-f",
                "base=main",
                "-f",
                "head=feature",
            ],
            pr_response,
        )
    )
    result = upsert_pr(
        runner=runner,
        repo=_REPO,
        number=None,
        title="New PR",
        body="Body text",
        base="main",
        head="feature",
    )
    assert result == pr_response
    runner.assert_exhausted()


def test_upsert_pr_edit_with_partial_fields() -> None:
    pr_response = {"number": 10, "html_url": "https://github.com/o/n/pull/10"}
    runner = make_runner(
        make_call(
            [
                "gh",
                "api",
                "--method",
                "PATCH",
                "/repos/o/n/pulls/10",
                "-f",
                "title=Updated Title",
            ],
            pr_response,
        )
    )
    result = upsert_pr(
        runner=runner,
        repo=_REPO,
        number=10,
        title="Updated Title",
        body=None,
        base=None,
        head=None,
    )
    assert result["number"] == 10
    runner.assert_exhausted()


def test_upsert_pr_edit_with_body_only() -> None:
    pr_response = {"number": 10, "html_url": "https://github.com/o/n/pull/10"}
    runner = make_runner(
        make_call(
            [
                "gh",
                "api",
                "--method",
                "PATCH",
                "/repos/o/n/pulls/10",
                "-f",
                "body=New body",
            ],
            pr_response,
        )
    )
    result = upsert_pr(
        runner=runner,
        repo=_REPO,
        number=10,
        title=None,
        body="New body",
        base=None,
        head=None,
    )
    assert result["number"] == 10
    runner.assert_exhausted()


def test_upsert_pr_raises_on_non_dict_payload() -> None:
    runner = make_runner(
        make_call(
            [
                "gh",
                "api",
                "--method",
                "PATCH",
                "/repos/o/n/pulls/10",
                "-f",
                "title=T",
            ],
            [1, 2, 3],
        )
    )
    with pytest.raises(ValueError, match="Unexpected PR payload"):
        upsert_pr(
            runner=runner,
            repo=_REPO,
            number=10,
            title="T",
            body=None,
            base=None,
            head=None,
        )


# -- _build_parser -------------------------------------------------------------


def test_build_parser_returns_argument_parser() -> None:
    parser = _build_parser()
    assert isinstance(parser, argparse.ArgumentParser)


def test_build_parser_has_expected_arguments() -> None:
    parser = _build_parser()
    known_args = parser.parse_args(["--repo", "o/n", "--number", "5", "--title", "T"])
    assert known_args.repo == "o/n"
    assert known_args.number == 5
    assert known_args.title == "T"


# -- _resolve_auto_summary_body -----------------------------------------------


def test_resolve_auto_summary_body_not_enabled() -> None:
    args = argparse.Namespace(auto_summary=False)
    result = _resolve_auto_summary_body(
        args,
        explicit_body="explicit body",
        gh_runner=make_runner(),
        repo=_REPO,
    )
    assert result == "explicit body"


def test_resolve_auto_summary_body_not_enabled_none_body() -> None:
    args = argparse.Namespace(auto_summary=False)
    result = _resolve_auto_summary_body(
        args,
        explicit_body=None,
        gh_runner=make_runner(),
        repo=_REPO,
    )
    assert result is None


def test_resolve_auto_summary_body_with_explicit_body_raises() -> None:
    args = argparse.Namespace(auto_summary=True)
    with pytest.raises(ValueError, match="cannot be combined"):
        _resolve_auto_summary_body(
            args,
            explicit_body="some body",
            gh_runner=make_runner(),
            repo=_REPO,
        )


def test_resolve_auto_summary_body_create_mode() -> None:
    """Auto-summary in create mode returns full_body from generate_auto_summary."""
    args = argparse.Namespace(
        auto_summary=True,
        number=None,
        base_branch=None,
        issue=None,
    )

    class _FakeSummary:
        full_body = "## Summary\nAuto-generated body"
        summary_md = "Auto-generated body"

    with (
        patch("scripts.common.git_runner.run_git"),
        patch("scripts.github.pr_auto_summary.detect_base_branch", return_value="main"),
        patch("scripts.github.pr_auto_summary.get_branch_commits", return_value=[]),
        patch("scripts.github.pr_auto_summary.generate_auto_summary", return_value=_FakeSummary()),
    ):
        result = _resolve_auto_summary_body(
            args,
            explicit_body=None,
            gh_runner=make_runner(),
            repo=_REPO,
        )
    assert result == "## Summary\nAuto-generated body"


def test_resolve_auto_summary_body_edit_mode_with_existing_body() -> None:
    """Auto-summary in edit mode replaces markers in existing PR body."""
    existing_pr = {"body": "Old PR body with markers", "number": 5}
    args = argparse.Namespace(
        auto_summary=True,
        number=5,
        base_branch="main",
        issue=None,
    )

    class _FakeSummary:
        full_body = "## Summary\nNew body"
        summary_md = "New summary"

    runner = make_runner(
        make_call(["gh", "api", "/repos/o/n/pulls/5"], existing_pr),
    )

    replaced_body = "Replaced body content"
    with (
        patch("scripts.common.git_runner.run_git"),
        patch("scripts.github.pr_auto_summary.detect_base_branch", return_value="main"),
        patch("scripts.github.pr_auto_summary.get_branch_commits", return_value=[]),
        patch("scripts.github.pr_auto_summary.generate_auto_summary", return_value=_FakeSummary()),
        patch("scripts.github.pr_auto_summary.replace_auto_summary_blocks", return_value=replaced_body),
    ):
        result = _resolve_auto_summary_body(
            args,
            explicit_body=None,
            gh_runner=runner,
            repo=_REPO,
        )
    assert result == replaced_body
    runner.assert_exhausted()


def test_resolve_auto_summary_body_edit_mode_syncs_issue_links() -> None:
    """Auto-summary in edit mode updates linked issues when --issue is provided."""
    existing_body = (
        "## Summary\n<!-- auto-summary:start -->\nold\n<!-- auto-summary:end -->\n\n## Linked issues\n\nCloses #9\n"
    )
    existing_pr = {"body": existing_body, "number": 5}
    args = argparse.Namespace(
        auto_summary=True,
        number=5,
        base_branch="main",
        issue=[9, 28, 29],
    )

    class _FakeSummary:
        full_body = "## Summary\nNew body"
        summary_md = "New summary"

    runner = make_runner(
        make_call(["gh", "api", "/repos/o/n/pulls/5"], existing_pr),
    )

    with (
        patch("scripts.common.git_runner.run_git"),
        patch("scripts.github.pr_auto_summary.detect_base_branch", return_value="main"),
        patch("scripts.github.pr_auto_summary.get_branch_commits", return_value=[]),
        patch("scripts.github.pr_auto_summary.generate_auto_summary", return_value=_FakeSummary()),
    ):
        result = _resolve_auto_summary_body(
            args,
            explicit_body=None,
            gh_runner=runner,
            repo=_REPO,
        )
    assert result is not None
    assert "Closes #9" in result
    assert "Closes #28" in result
    assert "Closes #29" in result
    runner.assert_exhausted()


def test_resolve_auto_summary_body_edit_mode_empty_existing_body() -> None:
    """Auto-summary in edit mode with empty existing body returns full_body."""
    existing_pr = {"body": "", "number": 5}
    args = argparse.Namespace(
        auto_summary=True,
        number=5,
        base_branch=None,
        issue=None,
    )

    class _FakeSummary:
        full_body = "## Summary\nFresh body"
        summary_md = "Fresh summary"

    runner = make_runner(
        make_call(["gh", "api", "/repos/o/n/pulls/5"], existing_pr),
    )

    with (
        patch("scripts.common.git_runner.run_git"),
        patch("scripts.github.pr_auto_summary.detect_base_branch", return_value="main"),
        patch("scripts.github.pr_auto_summary.get_branch_commits", return_value=[]),
        patch("scripts.github.pr_auto_summary.generate_auto_summary", return_value=_FakeSummary()),
    ):
        result = _resolve_auto_summary_body(
            args,
            explicit_body=None,
            gh_runner=runner,
            repo=_REPO,
        )
    assert result == "## Summary\nFresh body"
    runner.assert_exhausted()


# -- _run ----------------------------------------------------------------------


def test_run_json_output(capsys: pytest.CaptureFixture[str]) -> None:
    pr_payload = {
        "number": 3,
        "html_url": "https://github.com/o/n/pull/3",
        "title": "Test PR",
        "state": "open",
        "draft": False,
    }
    runner = make_runner(
        make_call(
            [
                "gh",
                "api",
                "--method",
                "POST",
                "/repos/o/n/pulls",
                "-f",
                "title=Test PR",
                "-f",
                "body=body",
                "-f",
                "base=main",
                "-f",
                "head=feature",
            ],
            pr_payload,
        )
    )
    args = argparse.Namespace(
        repo=_REPO,
        number=None,
        title="Test PR",
        body="body",
        body_file=None,
        base="main",
        head="feature",
        ready_for_review=False,
        auto_summary=False,
        base_branch=None,
        issue=None,
        json=True,
    )
    exit_code = _run(args, _build_parser(), runner)
    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["number"] == 3
    assert output["url"] == "https://github.com/o/n/pull/3"
    runner.assert_exhausted()


def test_run_text_output(capsys: pytest.CaptureFixture[str]) -> None:
    pr_payload = {
        "number": 3,
        "html_url": "https://github.com/o/n/pull/3",
        "title": "Test PR",
        "state": "open",
        "draft": False,
    }
    runner = make_runner(
        make_call(
            [
                "gh",
                "api",
                "--method",
                "POST",
                "/repos/o/n/pulls",
                "-f",
                "title=Test PR",
                "-f",
                "base=main",
                "-f",
                "head=feature",
            ],
            pr_payload,
        )
    )
    args = argparse.Namespace(
        repo=_REPO,
        number=None,
        title="Test PR",
        body=None,
        body_file=None,
        base="main",
        head="feature",
        ready_for_review=False,
        auto_summary=False,
        base_branch=None,
        issue=None,
        json=False,
    )
    exit_code = _run(args, _build_parser(), runner)
    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "PR #3" in captured
    runner.assert_exhausted()


def test_run_ready_for_review_flow(capsys: pytest.CaptureFixture[str]) -> None:
    upsert_response = {
        "number": 8,
        "html_url": "https://github.com/o/n/pull/8",
        "title": "Draft PR",
        "state": "open",
        "draft": True,
    }
    draft_pr = {"draft": True, "number": 8}
    ready_response: dict[str, Any] = {}
    final_pr = {
        "number": 8,
        "html_url": "https://github.com/o/n/pull/8",
        "title": "Draft PR",
        "state": "open",
        "draft": False,
    }
    runner = make_runner(
        # upsert call (PATCH)
        make_call(
            [
                "gh",
                "api",
                "--method",
                "PATCH",
                "/repos/o/n/pulls/8",
                "-f",
                "title=Draft PR",
            ],
            upsert_response,
        ),
        # _mark_pr_ready_for_review: fetch PR
        make_call(["gh", "api", "/repos/o/n/pulls/8"], draft_pr),
        # _mark_pr_ready_for_review: POST ready_for_review
        make_call(
            ["gh", "api", "--method", "POST", "/repos/o/n/pulls/8/ready_for_review"],
            ready_response,
        ),
        # re-fetch PR after ready
        make_call(["gh", "api", "/repos/o/n/pulls/8"], final_pr),
    )
    args = argparse.Namespace(
        repo=_REPO,
        number=8,
        title="Draft PR",
        body=None,
        body_file=None,
        base=None,
        head=None,
        ready_for_review=True,
        auto_summary=False,
        base_branch=None,
        issue=None,
        json=True,
    )
    exit_code = _run(args, _build_parser(), runner)
    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["draft"] is False
    runner.assert_exhausted()


def test_run_ready_for_review_without_number_raises() -> None:
    runner = make_runner()
    args = argparse.Namespace(
        repo=_REPO,
        number=None,
        title="T",
        body=None,
        body_file=None,
        base="main",
        head="feature",
        ready_for_review=True,
        auto_summary=False,
        base_branch=None,
        issue=None,
        json=False,
    )
    with pytest.raises(ValueError, match="only valid with --number"):
        _run(args, _build_parser(), runner)


# -- main ----------------------------------------------------------------------


def test_main_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scripts.github.pr_upsert.run_actionable_main", lambda **kwargs: 0)
    assert main() == 0


# -- _parse_args ---------------------------------------------------------------


def test_parse_args_delegates_to_build_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["prog", "--repo", "o/n", "--number", "7", "--title", "T"],
    )
    parsed = _parse_args()
    assert parsed.repo == "o/n"
    assert parsed.number == 7
    assert parsed.title == "T"


# -- _build_parser (all flags) ------------------------------------------------


def test_build_parser_body_file_flag() -> None:
    parser = _build_parser()
    parsed = parser.parse_args(["--body-file", "pr.md"])
    assert str(parsed.body_file) == "pr.md"


def test_build_parser_base_head_flags() -> None:
    parser = _build_parser()
    parsed = parser.parse_args(["--base", "main", "--head", "feature/x"])
    assert parsed.base == "main"
    assert parsed.head == "feature/x"


def test_build_parser_ready_for_review_flag() -> None:
    parser = _build_parser()
    parsed = parser.parse_args(["--ready-for-review"])
    assert parsed.ready_for_review is True


def test_build_parser_no_draft_flag() -> None:
    parser = _build_parser()
    parsed = parser.parse_args(["--no-draft"])
    assert parsed.ready_for_review is True


def test_build_parser_json_flag() -> None:
    parser = _build_parser()
    parsed = parser.parse_args(["--json"])
    assert parsed.json is True


def test_build_parser_auto_summary_flag() -> None:
    parser = _build_parser()
    parsed = parser.parse_args(["--auto-summary"])
    assert parsed.auto_summary is True


def test_build_parser_base_branch_flag() -> None:
    parser = _build_parser()
    parsed = parser.parse_args(["--base-branch", "develop"])
    assert parsed.base_branch == "develop"


def test_build_parser_issue_flag_repeatable() -> None:
    parser = _build_parser()
    parsed = parser.parse_args(["--issue", "10", "--issue", "20"])
    assert parsed.issue == [10, 20]


def test_build_parser_defaults() -> None:
    parser = _build_parser()
    parsed = parser.parse_args([])
    assert parsed.repo is None
    assert parsed.number is None
    assert parsed.title is None
    assert parsed.body is None
    assert parsed.body_file is None
    assert parsed.base is None
    assert parsed.head is None
    assert parsed.ready_for_review is False
    assert parsed.json is False
    assert parsed.auto_summary is False
    assert parsed.base_branch is None
    assert parsed.issue is None


# -- upsert_pr (base/head on edit) --------------------------------------------


def test_upsert_pr_edit_with_base_and_head() -> None:
    pr_response = {"number": 10, "html_url": "https://github.com/o/n/pull/10"}
    runner = make_runner(
        make_call(
            [
                "gh",
                "api",
                "--method",
                "PATCH",
                "/repos/o/n/pulls/10",
                "-f",
                "title=T",
                "-f",
                "base=develop",
                "-f",
                "head=feature/x",
            ],
            pr_response,
        )
    )
    result = upsert_pr(
        runner=runner,
        repo=_REPO,
        number=10,
        title="T",
        body=None,
        base="develop",
        head="feature/x",
    )
    assert result["number"] == 10
    runner.assert_exhausted()


# -- _run with auto-summary ---------------------------------------------------


def test_run_auto_summary_create_mode(capsys: pytest.CaptureFixture[str]) -> None:
    pr_payload = {
        "number": 15,
        "html_url": "https://github.com/o/n/pull/15",
        "title": "Auto PR",
        "state": "open",
        "draft": False,
    }
    runner = make_runner(
        make_call(
            [
                "gh",
                "api",
                "--method",
                "POST",
                "/repos/o/n/pulls",
                "-f",
                "title=Auto PR",
                "-f",
                "body=auto body",
                "-f",
                "base=main",
                "-f",
                "head=feature",
            ],
            pr_payload,
        )
    )
    args = argparse.Namespace(
        repo=_REPO,
        number=None,
        title="Auto PR",
        body=None,
        body_file=None,
        base="main",
        head="feature",
        ready_for_review=False,
        auto_summary=True,
        base_branch=None,
        issue=None,
        json=True,
    )
    with patch(
        "scripts.github.pr_upsert._resolve_auto_summary_body",
        return_value="auto body",
    ):
        exit_code = _run(args, _build_parser(), runner)
    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["number"] == 15
    runner.assert_exhausted()


def test_run_auto_summary_edit_mode(capsys: pytest.CaptureFixture[str]) -> None:
    pr_payload = {
        "number": 20,
        "html_url": "https://github.com/o/n/pull/20",
        "title": "Edit PR",
        "state": "open",
        "draft": False,
    }
    runner = make_runner(
        make_call(
            [
                "gh",
                "api",
                "--method",
                "PATCH",
                "/repos/o/n/pulls/20",
                "-f",
                "title=Edit PR",
                "-f",
                "body=updated body",
            ],
            pr_payload,
        )
    )
    args = argparse.Namespace(
        repo=_REPO,
        number=20,
        title="Edit PR",
        body=None,
        body_file=None,
        base=None,
        head=None,
        ready_for_review=False,
        auto_summary=True,
        base_branch="main",
        issue=[5],
        json=False,
    )
    with patch(
        "scripts.github.pr_upsert._resolve_auto_summary_body",
        return_value="updated body",
    ):
        exit_code = _run(args, _build_parser(), runner)
    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "PR #20" in captured
    runner.assert_exhausted()


# -- _resolve_auto_summary_body with custom base_branch -----------------------


def test_resolve_auto_summary_body_create_mode_with_custom_base() -> None:
    args = argparse.Namespace(
        auto_summary=True,
        number=None,
        base_branch="develop",
        issue=[1, 2],
    )

    class _FakeSummary:
        full_body = "## Summary\nCustom base body"
        summary_md = "Custom base summary"

    with (
        patch("scripts.common.git_runner.run_git"),
        patch("scripts.github.pr_auto_summary.detect_base_branch", return_value="main") as mock_detect,
        patch("scripts.github.pr_auto_summary.get_branch_commits", return_value=[]),
        patch("scripts.github.pr_auto_summary.generate_auto_summary", return_value=_FakeSummary()),
    ):
        result = _resolve_auto_summary_body(
            args,
            explicit_body=None,
            gh_runner=make_runner(),
            repo=_REPO,
        )
    # detect_base_branch should NOT be called when base_branch is provided
    mock_detect.assert_not_called()
    assert result == "## Summary\nCustom base body"


def test_resolve_auto_summary_body_edit_mode_none_body_key() -> None:
    """Edit mode where existing PR body is None falls through to full_body."""
    existing_pr = {"body": None, "number": 9}
    args = argparse.Namespace(
        auto_summary=True,
        number=9,
        base_branch=None,
        issue=None,
    )

    class _FakeSummary:
        full_body = "## Summary\nFallback body"
        summary_md = "Fallback summary"

    runner = make_runner(
        make_call(["gh", "api", "/repos/o/n/pulls/9"], existing_pr),
    )

    with (
        patch("scripts.common.git_runner.run_git"),
        patch("scripts.github.pr_auto_summary.detect_base_branch", return_value="main"),
        patch("scripts.github.pr_auto_summary.get_branch_commits", return_value=[]),
        patch("scripts.github.pr_auto_summary.generate_auto_summary", return_value=_FakeSummary()),
    ):
        result = _resolve_auto_summary_body(
            args,
            explicit_body=None,
            gh_runner=runner,
            repo=_REPO,
        )
    assert result == "## Summary\nFallback body"
    runner.assert_exhausted()
