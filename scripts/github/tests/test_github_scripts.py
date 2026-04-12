from __future__ import annotations

import argparse
import json
from typing import Any

import pytest

from scripts.github.conftest import ExpectedCall, QueueRunner, as_stdout, make_call, make_runner
from scripts.github.create_tag import create_tag
from scripts.github.dedupe_pr_review_replies import (
    ReviewReply,
    dedupe_pr_review_replies,
    find_duplicate_reply_ids,
)
from scripts.github.delete_branch import delete_branch
from scripts.github.diff_required_status_contexts import diff_required_contexts
from scripts.github.fix_unsigned_commits import (
    fix_unsigned_commits,
    get_pr_branch_info,
    rebase_to_resign_commits,
)
from scripts.github.gh_cli import (
    GhCliError,
    format_gh_cli_error,
    gh_diagnostics_enabled,
    gh_diagnostics_max_chars,
)
from scripts.github.issue_close import close_issue
from scripts.github.issue_upsert import upsert_issue
from scripts.github.list_issues import list_issues
from scripts.github.list_pr_commit_verifications import (
    _parse_fail_reasons,
    _should_fail,
    summarize_reasons,
)
from scripts.github.list_pr_review_comments_filtered import _matches_filters
from scripts.github.list_unresolved_review_threads import (
    _QUERY,
    ReviewComment,
    ReviewThread,
    filter_review_threads,
    list_unresolved_review_threads,
)
from scripts.github.pr_close import close_pr
from scripts.github.pr_sync_issue_links import (
    sync_issue_links_in_body,
    sync_pr_issue_links,
)
from scripts.github.pr_upsert import upsert_pr
from scripts.github.refactor_open_issues_work_package import (
    build_work_package_body,
)
from scripts.github.reply_and_resolve_review_comment import (
    _RESOLVE_MUTATION,
    _THREAD_QUERY,
    CommentContext,
    ResultArgs,
    _build_result,
    _post_reply_if_needed,
    _pr_number_from_url,
    fetch_comment_context,
    post_reply,
    post_reply_idempotent,
    resolve_review_thread,
    resolve_review_thread_id,
)
from scripts.github.test_pr_comment_access import (
    verify_authentication,
    verify_fetch_comment_context,
    verify_list_comments,
    verify_post_reply,
)


def test_format_gh_cli_error_includes_stdout_and_stderr() -> None:
    err = GhCliError(
        "gh command failed",
        argv=["gh", "api", "graphql"],
        returncode=1,
        stdout="OUT\n",
        stderr="ERR\n",
    )

    text = format_gh_cli_error(err, max_chars=None)
    assert "returncode: 1" in text
    assert "argv: gh api graphql" in text
    assert "stdout:" in text
    assert "OUT" in text
    assert "stderr:" in text
    assert "ERR" in text


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, False),
        ("", False),
        ("0", False),
        ("1", True),
        ("true", True),
        ("TRUE", True),
        ("yes", True),
        ("y", True),
        ("on", True),
        ("no", False),
        ("off", False),
    ],
)
def test_gh_diagnostics_enabled_parses_env(value: str | None, expected: bool) -> None:
    environ = {} if value is None else {"GH_HELPERS_DEBUG": value}
    assert gh_diagnostics_enabled(environ=environ) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, 50_000),
        ("", 50_000),
        ("500", 500),
        ("none", None),
        ("unlimited", None),
        ("0", 50_000),
        ("-1", 50_000),
        ("not-a-number", 50_000),
    ],
)
def test_gh_diagnostics_max_chars_parses_env(value: str | None, expected: int | None) -> None:
    environ = {} if value is None else {"GH_HELPERS_DEBUG_MAX_CHARS": value}
    assert gh_diagnostics_max_chars(environ=environ) == expected


def test_find_duplicate_reply_ids_keeps_earliest() -> None:
    replies = [
        ReviewReply(
            comment_id=2,
            in_reply_to=100,
            body="same",
            author="me",
            created_at="2025-01-01T00:00:02Z",
        ),
        ReviewReply(
            comment_id=1,
            in_reply_to=100,
            body="same",
            author="me",
            created_at="2025-01-01T00:00:01Z",
        ),
        ReviewReply(
            comment_id=3,
            in_reply_to=100,
            body="different",
            author="me",
            created_at="2025-01-01T00:00:03Z",
        ),
    ]

    delete_ids = find_duplicate_reply_ids(replies)
    assert delete_ids == [2]


@pytest.mark.parametrize("in_reply_to_key", ["in_reply_to", "in_reply_to_id"])
def test_dedupe_pr_review_replies_deletes_duplicates_when_apply_true(
    in_reply_to_key: str,
) -> None:
    review_comments: list[dict[str, Any]] = [
        {
            "id": 11,
            in_reply_to_key: 200,
            "body": "dup",
            "created_at": "2025-01-01T00:00:01Z",
            "user": {"login": "me"},
        },
        {
            "id": 12,
            in_reply_to_key: 200,
            "body": "dup",
            "created_at": "2025-01-01T00:00:02Z",
            "user": {"login": "me"},
        },
        {
            "id": 13,
            in_reply_to_key: 200,
            "body": "other",
            "created_at": "2025-01-01T00:00:03Z",
            "user": {"login": "me"},
        },
        # Different author: ignored
        {
            "id": 14,
            in_reply_to_key: 200,
            "body": "dup",
            "created_at": "2025-01-01T00:00:04Z",
            "user": {"login": "someone-else"},
        },
    ]

    runner = QueueRunner(
        [
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "/repos/octo/widgets/pulls/5/comments",
                    "--paginate",
                ],
                stdout=json.dumps(review_comments),
            ),
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "--method",
                    "DELETE",
                    "/repos/octo/widgets/pulls/comments/12",
                ],
                stdout="null",
            ),
        ]
    )

    result = dedupe_pr_review_replies(
        runner=runner,
        repo="octo/widgets",
        pr_number=5,
        author="me",
        apply=True,
    )

    assert result["deleted_count"] == 1
    assert result["duplicate_reply_ids"] == [12]


def test_issue_upsert_create_builds_expected_argv() -> None:
    runner = make_runner(
        make_call(
            [
                "gh",
                "api",
                "--method",
                "POST",
                "/repos/octo/widgets/issues",
                "-f",
                "title=Hello",
                "-f",
                "body=Body",
                "-f",
                "labels[]=bug",
                "-f",
                "assignees[]=me",
            ],
            {"number": 1},
        )
    )

    payload = upsert_issue(
        runner=runner,
        repo="octo/widgets",
        number=None,
        title="Hello",
        body="Body",
        labels=["bug"],
        assignees=["me"],
    )
    assert payload["number"] == 1


def test_pr_close_builds_expected_argv() -> None:
    runner = make_runner(
        make_call(
            [
                "gh",
                "pr",
                "close",
                "68",
                "--repo",
                "octo/widgets",
            ]
        )
    )

    payload = close_pr(runner=runner, repo="octo/widgets", pr_number=68)
    assert payload["ok"] is True
    assert payload["pr"] == 68


def test_issue_close_builds_expected_argv() -> None:
    runner = make_runner(
        make_call(
            [
                "gh",
                "api",
                "--method",
                "PATCH",
                "/repos/octo/widgets/issues/42",
                "-f",
                "state=closed",
                "-f",
                "state_reason=completed",
            ],
            {"number": 42, "state": "closed"},
        )
    )

    payload = close_issue(runner=runner, repo="octo/widgets", number=42)
    assert payload["ok"] is True
    assert payload["number"] == 42
    assert payload["reason"] == "completed"
    assert payload["commented"] is False


def test_issue_close_with_comment_posts_before_closing() -> None:
    runner = make_runner(
        make_call(
            [
                "gh",
                "api",
                "--method",
                "POST",
                "/repos/octo/widgets/issues/42/comments",
                "-f",
                "body=Resolved in PR #99.",
            ],
            {"id": 1001},
        ),
        make_call(
            [
                "gh",
                "api",
                "--method",
                "PATCH",
                "/repos/octo/widgets/issues/42",
                "-f",
                "state=closed",
                "-f",
                "state_reason=completed",
            ],
            {"number": 42, "state": "closed"},
        ),
    )

    payload = close_issue(
        runner=runner,
        repo="octo/widgets",
        number=42,
        comment="Resolved in PR #99.",
    )
    assert payload["ok"] is True
    assert payload["commented"] is True


def test_issue_close_not_planned_reason() -> None:
    runner = make_runner(
        make_call(
            [
                "gh",
                "api",
                "--method",
                "PATCH",
                "/repos/octo/widgets/issues/10",
                "-f",
                "state=closed",
                "-f",
                "state_reason=not_planned",
            ],
            {"number": 10, "state": "closed"},
        )
    )

    payload = close_issue(
        runner=runner,
        repo="octo/widgets",
        number=10,
        reason="not_planned",
    )
    assert payload["reason"] == "not_planned"


def test_issue_close_invalid_number() -> None:
    runner = QueueRunner([])
    with pytest.raises(ValueError, match="number must be positive"):
        close_issue(runner=runner, repo="octo/widgets", number=0)


def test_issue_close_invalid_reason() -> None:
    runner = QueueRunner([])
    with pytest.raises(ValueError, match="reason must be"):
        close_issue(runner=runner, repo="octo/widgets", number=42, reason="invalid")


def test_delete_branch_builds_expected_argv() -> None:
    runner = make_runner(
        make_call(
            [
                "gh",
                "api",
                "--method",
                "DELETE",
                "/repos/octo/widgets/git/refs/heads/copilot/sub-pr-66",
            ],
            "null",
        )
    )

    payload = delete_branch(
        runner=runner,
        repo="octo/widgets",
        branch="copilot/sub-pr-66",
    )
    assert payload["ok"] is True
    assert payload["branch"] == "copilot/sub-pr-66"


def test_create_tag_builds_expected_argv_and_payloads() -> None:
    tag_sha = "aaa" + "0" * 37
    commit_sha = "b" * 40
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "--method",
                    "POST",
                    "/repos/octo/widgets/git/tags",
                    "--input",
                    "-",
                ],
                stdout=as_stdout({"sha": tag_sha, "tag": "v2026.03.0"}),
                expected_input=json.dumps(
                    {
                        "tag": "v2026.03.0",
                        "message": "Release v2026.03.0",
                        "object": commit_sha,
                        "type": "commit",
                    }
                ),
            ),
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "--method",
                    "POST",
                    "/repos/octo/widgets/git/refs",
                    "--input",
                    "-",
                ],
                stdout=as_stdout({"ref": "refs/tags/v2026.03.0", "object": {"sha": tag_sha}}),
                expected_input=json.dumps(
                    {
                        "ref": "refs/tags/v2026.03.0",
                        "sha": tag_sha,
                    }
                ),
            ),
        ]
    )

    payload = create_tag(
        runner=runner,
        repo="octo/widgets",
        tag="v2026.03.0",
        sha=commit_sha,
        message="Release v2026.03.0",
    )
    assert payload["ok"] is True
    assert payload["tag"] == "v2026.03.0"
    assert payload["sha"] == commit_sha
    assert payload["tag_object_sha"] == tag_sha


def test_create_tag_rejects_empty_tag() -> None:
    runner = QueueRunner([])
    with pytest.raises(ValueError, match="tag is required"):
        create_tag(runner=runner, repo="octo/widgets", tag="", sha="a" * 40, message="msg")


@pytest.mark.parametrize(
    "tag",
    [
        "v1.2.3",
        "vfoo",
        "v2026.3.0",
        "v2026.03",
        "release-2026.03.0",
        "v2026..03.0",
        "v2026.03.0.lock",
        "v2026.00.1",
        "v2026.13.0",
    ],
)
def test_create_tag_rejects_non_calver_format(tag: str) -> None:
    runner = QueueRunner([])
    with pytest.raises(ValueError, match="CalVer pattern"):
        create_tag(runner=runner, repo="octo/widgets", tag=tag, sha="a" * 40, message="msg")


def test_create_tag_rejects_invalid_sha() -> None:
    runner = QueueRunner([])
    with pytest.raises(ValueError, match="sha must be"):
        create_tag(runner=runner, repo="octo/widgets", tag="v2026.03.0", sha="short", message="msg")


def test_create_tag_rejects_invalid_tag_object_sha() -> None:
    commit_sha = "b" * 40
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "--method",
                    "POST",
                    "/repos/octo/widgets/git/tags",
                    "--input",
                    "-",
                ],
                stdout=as_stdout({"sha": "not-a-valid-sha", "tag": "v2026.03.0"}),
                expected_input=json.dumps(
                    {
                        "tag": "v2026.03.0",
                        "message": "Release v2026.03.0",
                        "object": commit_sha,
                        "type": "commit",
                    }
                ),
            ),
        ]
    )
    with pytest.raises(ValueError, match="invalid SHA"):
        create_tag(
            runner=runner,
            repo="octo/widgets",
            tag="v2026.03.0",
            sha=commit_sha,
            message="Release v2026.03.0",
        )


def test_summarize_reasons_counts_unknown() -> None:
    commits: list[dict[str, Any]] = [
        {"reason": "valid"},
        {"reason": "unsigned"},
        {"reason": "unsigned"},
        {"reason": None},
        {},
    ]

    counts = summarize_reasons(commits)
    assert counts["unsigned"] == 2
    assert counts["valid"] == 1
    assert counts["unknown"] == 2


def test_parse_fail_reasons_handles_empty() -> None:
    assert _parse_fail_reasons(None) == set()
    assert _parse_fail_reasons("") == set()


def test_parse_fail_reasons_splits_and_strips() -> None:
    assert _parse_fail_reasons("unsigned, no_user,,") == {"unsigned", "no_user"}


def test_should_fail_checks_reasons() -> None:
    commits: list[dict[str, Any]] = [
        {"reason": "unsigned"},
        {"reason": "valid"},
        {"reason": None},
    ]
    assert _should_fail(commits, {"unsigned"}) is True
    assert _should_fail(commits, {"no_user"}) is False


def test_comment_author_substring_filter_is_case_insensitive() -> None:
    comment = {"author": "GitHub-CoPiLoT[bot]", "body": "x", "path": "a.txt"}
    assert _matches_filters(comment, author_substring="copilot", contains=None, path=None) is True
    assert _matches_filters(comment, author_substring="CuRsOr", contains=None, path=None) is False


def test_issue_upsert_create_requires_title() -> None:
    runner = QueueRunner([])
    with pytest.raises(ValueError, match="--title is required"):
        upsert_issue(
            runner=runner,
            repo="octo/widgets",
            number=None,
            title=None,
            body=None,
            labels=None,
            assignees=None,
        )


def test_issue_upsert_merge_existing_adds_label_and_assignee() -> None:
    runner = make_runner(
        make_call(
            ["gh", "api", "/repos/octo/widgets/issues/5"],
            {"labels": [{"name": "bug"}], "assignees": [{"login": "me"}]},
        ),
        make_call(
            [
                "gh",
                "api",
                "--method",
                "PATCH",
                "/repos/octo/widgets/issues/5",
                "-f",
                "labels[]=bug",
                "-f",
                "labels[]=security",
                "-f",
                "assignees[]=me",
                "-f",
                "assignees[]=you",
            ],
            {"number": 5},
        ),
    )

    payload = upsert_issue(
        runner=runner,
        repo="octo/widgets",
        number=5,
        title=None,
        body=None,
        labels=["security"],
        assignees=["you"],
        merge_existing=True,
    )
    assert payload["number"] == 5


def test_pr_upsert_edit_uses_patch_and_draft_flag() -> None:
    runner = make_runner(
        make_call(
            [
                "gh",
                "api",
                "--method",
                "PATCH",
                "/repos/octo/widgets/pulls/12",
                "-f",
                "title=New title",
            ],
            {"number": 12},
        )
    )

    payload = upsert_pr(
        runner=runner,
        repo="octo/widgets",
        number=12,
        title="New title",
        body=None,
        base=None,
        head=None,
    )
    assert payload["number"] == 12


def test_pr_ready_for_review_calls_endpoint_only_when_draft() -> None:
    from scripts.github.pr_upsert import _mark_pr_ready_for_review

    runner = make_runner(
        make_call(
            ["gh", "api", "/repos/octo/widgets/pulls/12"],
            {"number": 12, "draft": True},
        ),
        make_call(
            [
                "gh",
                "api",
                "--method",
                "POST",
                "/repos/octo/widgets/pulls/12/ready_for_review",
            ],
            {"ok": True},
        ),
    )

    _mark_pr_ready_for_review(runner=runner, repo="octo/widgets", number=12)


def test_pr_ready_for_review_noop_when_not_draft() -> None:
    from scripts.github.pr_upsert import _mark_pr_ready_for_review

    runner = make_runner(
        make_call(
            ["gh", "api", "/repos/octo/widgets/pulls/12"],
            {"number": 12, "draft": False},
        )
    )

    _mark_pr_ready_for_review(runner=runner, repo="octo/widgets", number=12)


# ---------------------------------------------------------------------------
# _resolve_auto_summary_body (--auto-summary integration)
# ---------------------------------------------------------------------------


def test_resolve_auto_summary_disabled_returns_explicit_body() -> None:
    from scripts.github.pr_upsert import _resolve_auto_summary_body

    args = argparse.Namespace(auto_summary=False, base_branch=None, issue=None, number=None)
    result = _resolve_auto_summary_body(
        args,
        explicit_body="explicit body",
        gh_runner=make_runner(),
        repo="octo/widgets",
    )
    assert result == "explicit body"


def test_resolve_auto_summary_rejects_explicit_body() -> None:
    from scripts.github.pr_upsert import _resolve_auto_summary_body

    args = argparse.Namespace(auto_summary=True, base_branch="main", issue=None, number=None)
    with pytest.raises(ValueError, match="cannot be combined"):
        _resolve_auto_summary_body(
            args,
            explicit_body="conflicting body",
            gh_runner=make_runner(),
            repo="octo/widgets",
        )


def test_resolve_auto_summary_create_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.common import git_runner as git_mod
    from scripts.github import pr_upsert as upsert_mod

    _unused = upsert_mod  # keep import for clarity

    def _mock_run_git(args: list[str], *, cwd: Any = None) -> Any:
        from scripts.common.git_runner import GitResult

        if "log" in args:
            return GitResult(0, "a1b2c3d feat(ci): test feature\n", "")
        return GitResult(0, "", "")

    monkeypatch.setattr(git_mod, "run_git", _mock_run_git)

    args = argparse.Namespace(auto_summary=True, base_branch="main", issue=[291], number=None)
    from scripts.github.pr_upsert import _resolve_auto_summary_body

    result = _resolve_auto_summary_body(
        args,
        explicit_body=None,
        gh_runner=make_runner(),
        repo="octo/widgets",
    )
    assert result is not None
    assert "## Summary" in result
    assert "Closes #291" in result


def test_resolve_auto_summary_edit_mode_replaces_markers(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.common import git_runner as git_mod
    from scripts.github.pr_auto_summary import _AUTO_SUMMARY_END, _AUTO_SUMMARY_START

    def _mock_run_git(args: list[str], *, cwd: Any = None) -> Any:
        from scripts.common.git_runner import GitResult

        if "log" in args:
            return GitResult(0, "a1b2c3d fix: updated fix\n", "")
        return GitResult(0, "", "")

    monkeypatch.setattr(git_mod, "run_git", _mock_run_git)

    existing_body = (
        f"## Summary\n\n{_AUTO_SUMMARY_START}\nold summary\n{_AUTO_SUMMARY_END}\n\nManual content preserved.\n"
    )
    gh_runner = make_runner(
        make_call(
            ["gh", "api", "/repos/octo/widgets/pulls/42"],
            {"number": 42, "body": existing_body},
        )
    )

    args = argparse.Namespace(auto_summary=True, base_branch="main", issue=None, number=42)
    from scripts.github.pr_upsert import _resolve_auto_summary_body

    result = _resolve_auto_summary_body(
        args,
        explicit_body=None,
        gh_runner=gh_runner,
        repo="octo/widgets",
    )
    assert result is not None
    assert "old summary" not in result
    assert "Manual content preserved." in result
    assert "Bug Fixes" in result


def test_resolve_auto_summary_edit_mode_empty_body(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.common import git_runner as git_mod

    def _mock_run_git(args: list[str], *, cwd: Any = None) -> Any:
        from scripts.common.git_runner import GitResult

        if "log" in args:
            return GitResult(0, "a1b2c3d feat: new feature\n", "")
        return GitResult(0, "", "")

    monkeypatch.setattr(git_mod, "run_git", _mock_run_git)

    gh_runner = make_runner(
        make_call(
            ["gh", "api", "/repos/octo/widgets/pulls/42"],
            {"number": 42, "body": ""},
        )
    )

    args = argparse.Namespace(auto_summary=True, base_branch="main", issue=None, number=42)
    from scripts.github.pr_upsert import _resolve_auto_summary_body

    result = _resolve_auto_summary_body(
        args,
        explicit_body=None,
        gh_runner=gh_runner,
        repo="octo/widgets",
    )
    assert result is not None
    assert "## Summary" in result


def test_list_unresolved_review_threads_paginates_and_filters() -> None:
    first_payload: dict[str, Any] = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": [
                            {
                                "id": "T1",
                                "isResolved": False,
                                "path": "a.py",
                                "line": 10,
                                "comments": {
                                    "nodes": [
                                        {
                                            "databaseId": 101,
                                            "id": "C1",
                                            "body": "fix this",
                                            "url": "https://example/c1",
                                            "author": {"login": "alice"},
                                        }
                                    ]
                                },
                            },
                            {
                                "id": "T2",
                                "isResolved": True,
                                "path": "b.py",
                                "line": 20,
                                "comments": {"nodes": []},
                            },
                        ],
                        "pageInfo": {"hasNextPage": True, "endCursor": "CUR1"},
                    }
                }
            }
        }
    }
    second_payload: dict[str, Any] = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": [],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            }
        }
    }

    runner = QueueRunner(
        [
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "graphql",
                    "-f",
                    f"query={_QUERY}",
                    "-f",
                    "owner=octo",
                    "-f",
                    "name=widgets",
                    "-F",
                    "number=5",
                ],
                stdout=json.dumps(first_payload),
            ),
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "graphql",
                    "-f",
                    f"query={_QUERY}",
                    "-f",
                    "owner=octo",
                    "-f",
                    "name=widgets",
                    "-F",
                    "number=5",
                    "-f",
                    "after=CUR1",
                ],
                stdout=json.dumps(second_payload),
            ),
        ]
    )

    threads = list_unresolved_review_threads(repo="octo/widgets", pr_number=5, runner=runner)
    assert [thread.thread_id for thread in threads] == ["T1"]
    assert threads[0].comments[0].database_id == 101


def test_filter_review_threads_supports_suffix_line_contains_and_author() -> None:
    threads = [
        ReviewThread(
            thread_id="T1",
            path="stacks/edge/docker-compose.yml",
            line=46,
            is_resolved=False,
            comments=[
                ReviewComment(
                    database_id=5001,
                    node_id="C5001",
                    author="copilot-pull-request-reviewer",
                    body="socket-proxy allowfrom may break in swarm",
                    url="https://example/c5001",
                )
            ],
        ),
        ReviewThread(
            thread_id="T2",
            path="stacks/edge/docker-compose.yml",
            line=99,
            is_resolved=False,
            comments=[
                ReviewComment(
                    database_id=5002,
                    node_id="C5002",
                    author="someone-else",
                    body="unrelated comment",
                    url="https://example/c5002",
                )
            ],
        ),
    ]

    filtered = filter_review_threads(
        threads,
        path="docker-compose.yml",
        line=46,
        contains="ALLOWFROM",
        author="copilot-pull-request-reviewer",
    )
    assert [thread.thread_id for thread in filtered] == ["T1"]


def test_pr_number_from_url_parses_number() -> None:
    assert _pr_number_from_url("https://api.github.com/repos/octo/widgets/pulls/45") == 45


def test_reply_flow_fetch_reply_resolve_builds_expected_calls() -> None:
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "/repos/octo/widgets/pulls/comments/999",
                ],
                stdout=json.dumps(
                    {
                        "node_id": "NODE123",
                        "pull_request_url": "https://api.github.com/repos/octo/widgets/pulls/45",
                    }
                ),
            ),
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "--method",
                    "POST",
                    "/repos/octo/widgets/pulls/45/comments",
                    "-F",
                    "in_reply_to=999",
                    "-f",
                    "body=done",
                ],
                stdout=json.dumps({"id": 1234}),
            ),
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "graphql",
                    "-f",
                    f"query={_THREAD_QUERY}",
                    "-f",
                    "owner=octo",
                    "-f",
                    "name=widgets",
                    "-F",
                    "number=45",
                ],
                stdout=json.dumps(
                    {
                        "data": {
                            "repository": {
                                "pullRequest": {
                                    "reviewThreads": {
                                        "nodes": [
                                            {
                                                "id": "THREAD1",
                                                "isResolved": False,
                                                "comments": {"nodes": [{"databaseId": 999}]},
                                            }
                                        ],
                                        "pageInfo": {
                                            "hasNextPage": False,
                                            "endCursor": None,
                                        },
                                    }
                                }
                            }
                        }
                    }
                ),
            ),
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "graphql",
                    "-f",
                    f"query={_RESOLVE_MUTATION}",
                    "-f",
                    "threadId=THREAD1",
                ],
                stdout=json.dumps({"data": {"resolveReviewThread": {"thread": {"id": "THREAD1", "isResolved": True}}}}),
            ),
        ]
    )

    ctx = fetch_comment_context(runner=runner, repo="octo/widgets", comment_id=999)
    assert ctx.pr_number == 45

    reply = post_reply(
        runner=runner,
        repo=ctx.repo,
        pr_number=ctx.pr_number,
        comment_id=999,
        body="done",
    )
    assert reply["id"] == 1234

    assert (
        resolve_review_thread(
            runner=runner,
            repo=ctx.repo,
            pr_number=ctx.pr_number,
            comment_id=999,
        )
        is True
    )


def test_post_reply_idempotent_skips_when_duplicate_exists() -> None:
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=["gh", "api", "/user"],
                stdout=json.dumps({"login": "octocat"}),
            ),
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "/repos/octo/widgets/pulls/45/comments",
                    "--paginate",
                ],
                stdout=json.dumps(
                    [
                        {
                            "id": 222,
                            "node_id": "NODE222",
                            "in_reply_to": 999,
                            "body": "Hello\n",
                            "user": {"login": "octocat"},
                        }
                    ]
                ),
            ),
        ]
    )

    reply, skipped = post_reply_idempotent(
        runner=runner,
        repo="octo/widgets",
        pr_number=45,
        comment_id=999,
        body="Hello",
    )
    assert skipped is True
    assert reply["id"] == 222


def test_post_reply_idempotent_posts_when_no_duplicate_exists() -> None:
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=["gh", "api", "/user"],
                stdout=json.dumps({"login": "octocat"}),
            ),
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "/repos/octo/widgets/pulls/45/comments",
                    "--paginate",
                ],
                stdout=json.dumps([]),
            ),
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "--method",
                    "POST",
                    "/repos/octo/widgets/pulls/45/comments",
                    "-F",
                    "in_reply_to=999",
                    "-f",
                    "body=Hello",
                ],
                stdout=json.dumps({"id": 333, "node_id": "NODE333"}),
            ),
        ]
    )

    reply, skipped = post_reply_idempotent(
        runner=runner,
        repo="octo/widgets",
        pr_number=45,
        comment_id=999,
        body="Hello",
    )

    assert skipped is False
    assert reply["id"] == 333


def test_post_reply_if_needed_skips_when_body_missing() -> None:
    ctx = CommentContext(repo="octo/widgets", pr_number=45)
    runner = QueueRunner([])
    reply, skipped = _post_reply_if_needed(
        runner=runner,
        ctx=ctx,
        comment_id=999,
        body=None,
    )
    assert reply is None
    assert skipped is None


def test_build_result_populates_reply_fields() -> None:
    args = ResultArgs(comment_id=123, thread_id="THREAD1")
    ctx = CommentContext(repo="octo/widgets", pr_number=45)
    result = _build_result(
        ctx=ctx,
        args=args,
        reply={"id": 222, "node_id": "NODE222"},
        reply_skipped=False,
        resolved=True,
    )
    assert result["repo"] == "octo/widgets"
    assert result["pr"] == 45
    assert result["in_reply_to"] == 123
    assert result["thread_id"] == "THREAD1"
    assert result["reply_id"] == 222
    assert result["reply_node_id"] == "NODE222"
    assert result["reply_skipped"] is False
    assert result["resolved"] is True


def test_resolve_review_thread_id_builds_expected_call() -> None:
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "graphql",
                    "-f",
                    f"query={_RESOLVE_MUTATION}",
                    "-f",
                    "threadId=PRRT_123",
                ],
                stdout=json.dumps(
                    {"data": {"resolveReviewThread": {"thread": {"id": "PRRT_123", "isResolved": True}}}}
                ),
            )
        ]
    )

    assert resolve_review_thread_id(runner=runner, thread_id="PRRT_123") is True


def test_diff_required_contexts_uses_commit_status_contexts() -> None:
    repo = "octo/widgets"

    runner = QueueRunner(
        [
            ExpectedCall(
                argv=[
                    "gh",
                    "pr",
                    "view",
                    "45",
                    "--repo",
                    repo,
                    "--json",
                    "commits",
                ],
                stdout=json.dumps({"commits": [{"oid": "SHA1"}]}),
            ),
            ExpectedCall(
                argv=["gh", "api", "--paginate", "/repos/octo/widgets/rulesets"],
                stdout=json.dumps([{"id": 1}]),
            ),
            ExpectedCall(
                argv=["gh", "api", "/repos/octo/widgets/rulesets/1"],
                stdout=json.dumps(
                    {
                        "rules": [
                            {
                                "type": "required_status_checks",
                                "parameters": {
                                    "required_status_checks": [
                                        {"context": "A"},
                                        {"context": "B"},
                                    ]
                                },
                            }
                        ]
                    }
                ),
            ),
            ExpectedCall(
                argv=["gh", "api", "/repos/octo/widgets/commits/SHA1/status"],
                stdout=json.dumps({"statuses": [{"context": "A"}]}),
            ),
        ]
    )

    result = diff_required_contexts(runner=runner, repo=repo, pr_number=45)
    assert result["head_sha"] == "SHA1"
    assert result["diff"]["missing"] == ["B"]


def test_sync_issue_links_in_body_normalizes_to_single_header_and_dedupes() -> None:
    body = """Linked Issue: Closes #44
Closes #46

Summary
- Something

Closes #61
"""

    new_body = sync_issue_links_in_body(
        body=body,
        closes={44, 46, 47, 61},
        relates=set(),
    )

    assert "Linked Issue:" not in new_body

    # Duplicate close references are consolidated into the canonical block at the end.
    assert new_body.count("Closes #61") == 1

    # Rest of content preserved.
    assert "Summary" in new_body
    assert "- Something" in new_body

    # Canonical closes block appended at end.
    assert new_body.endswith("\nCloses #44\nCloses #46\nCloses #47\nCloses #61\n")


def test_pr_sync_issue_links_merge_existing_adds_without_relisting() -> None:
    repo = "octo/widgets"
    pr_number = 45

    old_body = """Summary
- Something

Closes #44
Relates to #50
"""

    expected_body = sync_issue_links_in_body(
        body=old_body,
        closes={44, 52},
        relates={50},
    )

    runner = QueueRunner(
        [
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    f"/repos/{repo}/pulls/{pr_number}",
                ],
                stdout=json.dumps({"body": old_body}),
            ),
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "--method",
                    "PATCH",
                    f"/repos/{repo}/pulls/{pr_number}",
                    "-f",
                    f"body={expected_body}",
                ],
                stdout=json.dumps({"body": expected_body}),
            ),
        ]
    )

    result = sync_pr_issue_links(
        runner=runner,
        repo=repo,
        pr_number=pr_number,
        closes={52},
        relates=set(),
        dry_run=False,
        merge_existing=True,
    )

    assert result.changed is True
    assert result.closes == [44, 52]
    assert result.relates == [50]


def test_pr_sync_issue_links_auto_summary_refreshes_markers(monkeypatch: Any) -> None:
    from scripts.common import git_runner as git_mod
    from scripts.github.pr_auto_summary import (
        _AUTO_SUMMARY_END,
        _AUTO_SUMMARY_START,
        refresh_auto_summary_in_body,
    )

    git_log_output = "a1b2c3d feat(ci): new feature\n"

    def _mock_run_git(args: list[str], *, cwd: Any = None) -> Any:
        from scripts.common.git_runner import GitResult

        if "rev-parse" in args:
            return GitResult(0, "", "")
        if "log" in args:
            return GitResult(0, git_log_output, "")
        return GitResult(0, "", "")

    monkeypatch.setattr(git_mod, "run_git", _mock_run_git)

    body_with_markers = f"## Summary\n\n{_AUTO_SUMMARY_START}\nold summary\n{_AUTO_SUMMARY_END}\n\nManual content.\n"

    # Precompute expected body after refresh so we can match the PATCH argv.
    from scripts.common.git_runner import GitResult as _GitResult

    class _StubGit:
        def run_git(self, args: list[str], *, cwd: Any = None) -> Any:
            if "rev-parse" in args:
                return _GitResult(0, "", "")
            if "log" in args:
                return _GitResult(0, git_log_output, "")
            return _GitResult(0, "", "")

    expected_body = refresh_auto_summary_in_body(
        existing_body=body_with_markers,
        git_runner=_StubGit(),
        base_branch="main",
    )
    assert "new feature" in expected_body
    assert "old summary" not in expected_body

    runner = QueueRunner(
        [
            # _refresh_auto_summary fetches PR body
            ExpectedCall(
                argv=["gh", "api", "/repos/octo/widgets/pulls/45"],
                stdout=json.dumps({"body": body_with_markers}),
            ),
            # _refresh_auto_summary PATCHes with refreshed markers
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "--method",
                    "PATCH",
                    "/repos/octo/widgets/pulls/45",
                    "-f",
                    f"body={expected_body}",
                ],
                stdout=json.dumps({"body": expected_body}),
            ),
        ]
    )

    from scripts.github.pr_sync_issue_links import _refresh_auto_summary

    _refresh_auto_summary(
        gh_runner=runner,
        repo="octo/widgets",
        pr_number=45,
        base_branch="main",
        dry_run=False,
    )
    runner.assert_exhausted()


def test_pr_sync_issue_links_auto_summary_dry_run_does_not_patch(monkeypatch: Any) -> None:
    from scripts.common import git_runner as git_mod
    from scripts.github.pr_auto_summary import _AUTO_SUMMARY_END, _AUTO_SUMMARY_START

    def _mock_run_git(args: list[str], *, cwd: Any = None) -> Any:
        from scripts.common.git_runner import GitResult

        if "rev-parse" in args:
            return GitResult(0, "", "")
        if "log" in args:
            return GitResult(0, "a1b2c3d feat: feature\n", "")
        return GitResult(0, "", "")

    monkeypatch.setattr(git_mod, "run_git", _mock_run_git)

    body_with_markers = f"before\n{_AUTO_SUMMARY_START}\nold\n{_AUTO_SUMMARY_END}\nafter\n"
    runner = QueueRunner(
        [
            # _refresh_auto_summary fetches PR body
            ExpectedCall(
                argv=["gh", "api", "/repos/octo/widgets/pulls/45"],
                stdout=json.dumps({"body": body_with_markers}),
            ),
            # No PATCH call — dry_run=True
        ]
    )

    from scripts.github.pr_sync_issue_links import _refresh_auto_summary

    _refresh_auto_summary(
        gh_runner=runner,
        repo="octo/widgets",
        pr_number=45,
        base_branch="main",
        dry_run=True,
    )
    runner.assert_exhausted()


def test_pr_sync_issue_links_auto_summary_noop_without_markers(monkeypatch: Any) -> None:
    from scripts.common import git_runner as git_mod

    def _mock_run_git(args: list[str], *, cwd: Any = None) -> Any:
        from scripts.common.git_runner import GitResult

        if "rev-parse" in args:
            return GitResult(0, "", "")
        if "log" in args:
            return GitResult(0, "a1b2c3d feat: feature\n", "")
        return GitResult(0, "", "")

    monkeypatch.setattr(git_mod, "run_git", _mock_run_git)

    body_no_markers = "## Summary\n\nManual content.\n"
    runner = QueueRunner(
        [
            # _refresh_auto_summary fetches PR body
            ExpectedCall(
                argv=["gh", "api", "/repos/octo/widgets/pulls/45"],
                stdout=json.dumps({"body": body_no_markers}),
            ),
            # No PATCH — body unchanged (no markers to replace)
        ]
    )

    from scripts.github.pr_sync_issue_links import _refresh_auto_summary

    _refresh_auto_summary(
        gh_runner=runner,
        repo="octo/widgets",
        pr_number=45,
        base_branch="main",
        dry_run=False,
    )
    runner.assert_exhausted()


def test_list_issues_excludes_pull_requests_and_maps_fields() -> None:
    payload: list[dict[str, Any]] = [
        {
            "number": 10,
            "title": "Real issue",
            "state": "open",
            "html_url": "https://example/issues/10",
            "labels": [{"name": "bug"}],
            "assignees": [{"login": "alice"}],
            "body": None,
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-02T00:00:00Z",
        },
        {
            "number": 11,
            "title": "A PR",
            "state": "open",
            "pull_request": {"url": "https://example/pulls/11"},
        },
    ]

    runner = QueueRunner(
        [
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "--method",
                    "GET",
                    "--paginate",
                    "/repos/octo/widgets/issues",
                    "-f",
                    "state=open",
                    "-f",
                    "per_page=100",
                ],
                stdout=json.dumps(payload),
            )
        ]
    )

    issues = list_issues(runner=runner, repo="octo/widgets", state="open")
    assert issues == [
        {
            "number": 10,
            "title": "Real issue",
            "state": "open",
            "url": "https://example/issues/10",
            "labels": ["bug"],
            "assignees": ["alice"],
            "body": "",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-02T00:00:00Z",
        }
    ]


def test_build_work_package_body_matches_template_shape() -> None:
    body = build_work_package_body()

    assert "## Objective" in body
    assert "## Risk level" in body
    assert "## Affected services/paths" in body
    assert "## Rollback plan" in body
    assert "## Deliverables" in body
    assert "## Acceptance criteria" in body
    assert "## Validation plan" in body
    assert "## TDD Requirements" in body
    assert "## Dependencies" in body
    assert "## Estimate" in body

    assert "1h | 2h | 3h" in body
    assert "#123, #456" in body


def test_test_authentication_success() -> None:
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=["gh", "api", "/user"],
                stdout=json.dumps({"login": "testuser"}),
            )
        ]
    )

    result = verify_authentication(runner)
    assert result["status"] == "success"
    assert result["login"] == "testuser"


def test_test_authentication_failure() -> None:
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=["gh", "api", "/user"],
                stdout=json.dumps({}),
            )
        ]
    )

    result = verify_authentication(runner)
    assert result["status"] == "success"  # Still succeeds, just login is "unknown"
    assert result["login"] == "unknown"


def test_test_list_comments_success() -> None:
    comments_data = [
        {"id": 1, "body": "Comment 1"},
        {"id": 2, "body": "Comment 2"},
    ]
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "--paginate",
                    "/repos/octo/widgets/pulls/5/comments",
                ],
                stdout=json.dumps(comments_data),
            )
        ]
    )

    result = verify_list_comments(runner, "octo/widgets", 5)
    assert result["status"] == "success"
    assert result["count"] == 2
    assert len(result["comments"]) == 2


def test_test_fetch_comment_context_success() -> None:
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=["gh", "api", "/repos/octo/widgets/pulls/comments/999"],
                stdout=json.dumps(
                    {
                        "node_id": "NODE123",
                        "pull_request_url": "https://api.github.com/repos/octo/widgets/pulls/45",
                    }
                ),
            )
        ]
    )

    result = verify_fetch_comment_context(runner, "octo/widgets", 999)
    assert result["status"] == "success"
    assert result["pr_number"] == 45
    assert result["repo"] == "octo/widgets"


def test_test_post_reply_finds_existing() -> None:
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=["gh", "api", "/user"],
                stdout=json.dumps({"login": "testuser"}),
            ),
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "/repos/octo/widgets/pulls/45/comments",
                    "--paginate",
                ],
                stdout=json.dumps(
                    [
                        {
                            "id": 222,
                            "in_reply_to": 999,
                            "body": "Test reply",
                            "user": {"login": "testuser"},
                        }
                    ]
                ),
            ),
        ]
    )

    result = verify_post_reply(runner, "octo/widgets", 45, 999, "Test reply")
    assert result["status"] == "success"
    assert result["skipped"] is True
    assert result["reply_id"] == 222


def test_test_post_reply_creates_new() -> None:
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=["gh", "api", "/user"],
                stdout=json.dumps({"login": "testuser"}),
            ),
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "/repos/octo/widgets/pulls/45/comments",
                    "--paginate",
                ],
                stdout=json.dumps([]),
            ),
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "--method",
                    "POST",
                    "/repos/octo/widgets/pulls/45/comments",
                    "-F",
                    "in_reply_to=999",
                    "-f",
                    "body=Test reply",
                ],
                stdout=json.dumps({"id": 333, "node_id": "NODE333"}),
            ),
        ]
    )

    result = verify_post_reply(runner, "octo/widgets", 45, 999, "Test reply")
    assert result["status"] == "success"
    assert result["skipped"] is False
    assert result["reply_id"] == 333


def test_get_pr_branch_info_extracts_refs() -> None:
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=["gh", "api", "/repos/octo/widgets/pulls/45"],
                stdout=json.dumps(
                    {
                        "head": {"ref": "feature-branch", "sha": "abc123"},
                        "base": {"ref": "main"},
                    }
                ),
            )
        ]
    )

    result = get_pr_branch_info(runner=runner, repo="octo/widgets", pr_number=45)
    assert result["head_ref"] == "feature-branch"
    assert result["base_ref"] == "main"
    assert result["head_sha"] == "abc123"


def test_get_pr_branch_info_raises_on_missing_ref() -> None:
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=["gh", "api", "/repos/octo/widgets/pulls/45"],
                stdout=json.dumps({"head": {}, "base": {"ref": "main"}}),
            )
        ]
    )

    with pytest.raises(ValueError, match="Unable to determine PR head ref"):
        get_pr_branch_info(runner=runner, repo="octo/widgets", pr_number=45)


def test_rebase_to_resign_commits_dry_run() -> None:
    result = rebase_to_resign_commits(base_ref="main", apply=False)
    assert result["status"] == "dry_run"
    assert "Would rebase" in result["message"]


def test_fix_unsigned_commits_no_unsigned_commits() -> None:
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "--paginate",
                    "/repos/octo/widgets/pulls/45/commits",
                ],
                stdout=json.dumps(
                    [
                        {
                            "sha": "abc123",
                            "commit": {
                                "verification": {"verified": True, "reason": "valid"},
                                "message": "Signed commit",
                            },
                        }
                    ]
                ),
            )
        ]
    )

    result = fix_unsigned_commits(runner=runner, repo="octo/widgets", pr_number=45, apply=False)
    assert result["status"] == "no_action_needed"
    assert result["unsigned_count"] == 0
    assert "No failing commits found" in result["message"]


def test_fix_unsigned_commits_missing_signing_config(monkeypatch: Any) -> None:
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "--paginate",
                    "/repos/octo/widgets/pulls/45/commits",
                ],
                stdout=json.dumps(
                    [
                        {
                            "sha": "abc123",
                            "commit": {
                                "verification": {
                                    "verified": False,
                                    "reason": "unsigned",
                                },
                                "message": "Unsigned commit",
                            },
                        }
                    ]
                ),
            )
        ]
    )

    # Mock check_git_signing_config to return unconfigured
    def mock_check_config() -> dict[str, Any]:
        return {
            "configured": False,
            "commit_gpgsign": None,
            "gpg_format": None,
            "user_signingkey": None,
        }

    monkeypatch.setattr(
        "scripts.github.fix_unsigned_commits.check_git_signing_config",
        mock_check_config,
    )

    result = fix_unsigned_commits(runner=runner, repo="octo/widgets", pr_number=45, apply=False)
    assert result["status"] == "error"
    assert "not properly configured" in result["error"]


def _make_unsigned_commit_calls() -> list[ExpectedCall]:
    return [
        make_call(
            [
                "gh",
                "api",
                "--paginate",
                "/repos/octo/widgets/pulls/45/commits",
            ],
            [
                {
                    "sha": "abc123",
                    "commit": {
                        "verification": {"verified": False, "reason": "unsigned"},
                        "message": "Unsigned commit",
                    },
                }
            ],
        ),
        make_call(
            ["gh", "api", "/repos/octo/widgets/pulls/45"],
            {
                "head": {"ref": "feature-branch", "sha": "abc123"},
                "base": {"ref": "main"},
            },
        ),
    ]


def _mock_signing_config(monkeypatch: Any, configured: bool = True) -> None:
    def mock_check_config() -> dict[str, Any]:
        return {
            "configured": configured,
            "commit_gpgsign": "true" if configured else None,
            "gpg_format": "ssh" if configured else None,
            "user_signingkey": "~/.ssh/id_ed25519_signing.pub" if configured else None,
        }

    monkeypatch.setattr(
        "scripts.github.fix_unsigned_commits.check_git_signing_config",
        mock_check_config,
    )


def test_fix_unsigned_commits_wrong_branch(monkeypatch: Any) -> None:
    runner = make_runner(*_make_unsigned_commit_calls())
    _mock_signing_config(monkeypatch, configured=True)

    def mock_get_current_branch() -> str | None:
        return "wrong-branch"

    monkeypatch.setattr(
        "scripts.github.fix_unsigned_commits.get_current_branch",
        mock_get_current_branch,
    )

    result = fix_unsigned_commits(runner=runner, repo="octo/widgets", pr_number=45, apply=False)
    assert result["status"] == "error"
    assert "does not match PR head branch" in result["error"]


def test_fix_unsigned_commits_dry_run_success(monkeypatch: Any) -> None:
    runner = make_runner(*_make_unsigned_commit_calls())
    _mock_signing_config(monkeypatch, configured=True)

    def mock_get_current_branch() -> str | None:
        return "feature-branch"

    def mock_verify_local_branch(*, branch: str) -> bool:
        return True

    monkeypatch.setattr(
        "scripts.github.fix_unsigned_commits.get_current_branch",
        mock_get_current_branch,
    )
    monkeypatch.setattr(
        "scripts.github.fix_unsigned_commits.verify_local_branch",
        mock_verify_local_branch,
    )

    result = fix_unsigned_commits(runner=runner, repo="octo/widgets", pr_number=45, apply=False)
    assert result["status"] == "dry_run"
    assert result["unsigned_count"] == 1
    assert "Dry run complete" in result["message"]
