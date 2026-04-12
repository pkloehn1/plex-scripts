"""Tests for triage_review_comments flow script."""

from __future__ import annotations

import argparse
import json
from typing import Any

import pytest

from scripts.github.reply_and_resolve_review_comment import (
    _RESOLVE_MUTATION,
    _THREAD_QUERY,
)
from scripts.github.tests.test_github_scripts import (
    ExpectedCall,
    QueueRunner,
)
from scripts.github.triage_review_comments import (
    ReplySpec,
    _build_parser,
    _run,
    list_filtered_comments,
    main,
    parse_replies_json,
    triage_comments,
)


def test_parse_replies_json_valid() -> None:
    raw = '[{"comment_id": 123, "body": "Fixed."}]'
    specs = parse_replies_json(raw)
    assert len(specs) == 1
    assert specs[0].comment_id == 123
    assert specs[0].body == "Fixed."


def test_parse_replies_json_multiple() -> None:
    raw = '[{"comment_id": 1, "body": "A"}, {"comment_id": 2, "body": "B"}]'
    specs = parse_replies_json(raw)
    assert len(specs) == 2
    assert specs[0].comment_id == 1
    assert specs[1].comment_id == 2


def test_parse_replies_json_not_array() -> None:
    with pytest.raises(ValueError, match="must be a JSON array"):
        parse_replies_json('{"comment_id": 1, "body": "A"}')


def test_parse_replies_json_missing_comment_id() -> None:
    with pytest.raises(ValueError, match="integer 'comment_id'"):
        parse_replies_json('[{"body": "A"}]')


def test_parse_replies_json_missing_body() -> None:
    with pytest.raises(ValueError, match="non-empty string 'body'"):
        parse_replies_json('[{"comment_id": 1}]')


def test_parse_replies_json_empty_body() -> None:
    with pytest.raises(ValueError, match="non-empty string 'body'"):
        parse_replies_json('[{"comment_id": 1, "body": "  "}]')


def _make_comments_payload() -> list[dict[str, Any]]:
    """Raw API payload format (user.login) — used by QueueRunner tests."""
    return [
        {
            "id": 100,
            "node_id": "N100",
            "path": "a.py",
            "line": 10,
            "user": {"login": "copilot-reviewer[bot]"},
            "html_url": "https://example/100",
            "body": "Consider refactoring this.",
        },
        {
            "id": 200,
            "node_id": "N200",
            "path": "b.py",
            "line": 20,
            "user": {"login": "human-reviewer"},
            "html_url": "https://example/200",
            "body": "Looks fine.",
        },
    ]


def _make_transformed_comments() -> list[dict[str, Any]]:
    """Transformed format as returned by list_review_comments (author field)."""
    return [
        {
            "id": 100,
            "node_id": "N100",
            "path": "a.py",
            "line": 10,
            "author": "copilot-reviewer[bot]",
            "url": "https://example/100",
            "body": "Consider refactoring this.",
        },
        {
            "id": 200,
            "node_id": "N200",
            "path": "b.py",
            "line": 20,
            "author": "human-reviewer",
            "url": "https://example/200",
            "body": "Looks fine.",
        },
    ]


def test_list_filtered_comments_no_filter() -> None:
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "--paginate",
                    "/repos/octo/widgets/pulls/5/comments",
                ],
                stdout=json.dumps(_make_comments_payload()),
            )
        ]
    )
    result = list_filtered_comments(
        runner=runner,
        repo="octo/widgets",
        pr_number=5,
        author_substring=None,
        contains=None,
        path=None,
    )
    assert len(result) == 2


def test_list_filtered_comments_author_filter() -> None:
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "--paginate",
                    "/repos/octo/widgets/pulls/5/comments",
                ],
                stdout=json.dumps(_make_comments_payload()),
            )
        ]
    )
    result = list_filtered_comments(
        runner=runner,
        repo="octo/widgets",
        pr_number=5,
        author_substring="copilot",
        contains=None,
        path=None,
    )
    assert len(result) == 1
    assert result[0]["id"] == 100


def test_triage_comments_list_only() -> None:
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "--paginate",
                    "/repos/octo/widgets/pulls/5/comments",
                ],
                stdout=json.dumps(_make_comments_payload()),
            )
        ]
    )
    result = triage_comments(
        runner=runner,
        repo="octo/widgets",
        pr_number=5,
        author_substring="copilot",
    )
    assert result["action"] == "list_only"
    assert result["comments_count"] == 1
    assert result["repo"] == "octo/widgets"
    assert result["pr"] == 5


def _make_reply_resolve_calls(
    *,
    comment_id: int,
    body: str,
    reply_id: int,
) -> list[ExpectedCall]:
    """Build the expected call sequence for post_reply_idempotent + resolve_review_thread."""
    return [
        # post_reply_idempotent: current_login
        ExpectedCall(
            argv=["gh", "api", "/user"],
            stdout=json.dumps({"login": "agent-bot"}),
        ),
        # post_reply_idempotent: find_existing_reply (paginated comments)
        ExpectedCall(
            argv=[
                "gh",
                "api",
                "/repos/octo/widgets/pulls/5/comments",
                "--paginate",
            ],
            stdout=json.dumps([]),
        ),
        # post_reply_idempotent: post_reply
        ExpectedCall(
            argv=[
                "gh",
                "api",
                "--method",
                "POST",
                "/repos/octo/widgets/pulls/5/comments",
                "-F",
                f"in_reply_to={comment_id}",
                "-f",
                f"body={body}",
            ],
            stdout=json.dumps({"id": reply_id, "node_id": f"NODE{reply_id}"}),
        ),
        # resolve_review_thread: fetch thread pages
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
                "number=5",
            ],
            stdout=json.dumps(
                {
                    "data": {
                        "repository": {
                            "pullRequest": {
                                "reviewThreads": {
                                    "nodes": [
                                        {
                                            "id": f"THREAD_{comment_id}",
                                            "isResolved": False,
                                            "comments": {"nodes": [{"databaseId": comment_id}]},
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
        # resolve_review_thread: resolve mutation
        ExpectedCall(
            argv=[
                "gh",
                "api",
                "graphql",
                "-f",
                f"query={_RESOLVE_MUTATION}",
                "-f",
                f"threadId=THREAD_{comment_id}",
            ],
            stdout=json.dumps(
                {
                    "data": {
                        "resolveReviewThread": {
                            "thread": {
                                "id": f"THREAD_{comment_id}",
                                "isResolved": True,
                            }
                        }
                    }
                }
            ),
        ),
    ]


def test_triage_comments_reply_and_resolve() -> None:
    list_call = ExpectedCall(
        argv=[
            "gh",
            "api",
            "--paginate",
            "/repos/octo/widgets/pulls/5/comments",
        ],
        stdout=json.dumps(_make_comments_payload()),
    )
    reply_resolve_calls = _make_reply_resolve_calls(
        comment_id=100,
        body="Addressed in latest commit.",
        reply_id=500,
    )

    runner = QueueRunner([list_call, *reply_resolve_calls])

    result = triage_comments(
        runner=runner,
        repo="octo/widgets",
        pr_number=5,
        author_substring="copilot",
        replies=[ReplySpec(comment_id=100, body="Addressed in latest commit.")],
    )

    assert result["action"] == "reply_and_resolve"
    assert result["comments_count"] == 1
    assert len(result["reply_results"]) == 1

    reply_out = result["reply_results"][0]
    assert reply_out["comment_id"] == 100
    assert reply_out["reply_id"] == 500
    assert reply_out["reply_skipped"] is False
    assert reply_out["resolved"] is True


def test_triage_comments_empty_replies_treated_as_list_only() -> None:
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "--paginate",
                    "/repos/octo/widgets/pulls/5/comments",
                ],
                stdout=json.dumps(_make_comments_payload()),
            )
        ]
    )
    result = triage_comments(
        runner=runner,
        repo="octo/widgets",
        pr_number=5,
        replies=[],
    )
    assert result["action"] == "list_only"


# -- parse_replies_json: non-dict item in array (line 59) ----------------------


def test_parse_replies_json_non_dict_item_raises() -> None:
    raw_with_string_item = '[42, {"comment_id": 1, "body": "A"}]'
    with pytest.raises(ValueError, match="must be an object"):
        parse_replies_json(raw_with_string_item)


# -- _build_parser / _run / main (lines 163-185, 193-214, 218) ----------------


def test_build_parser_returns_argument_parser() -> None:
    parser = _build_parser()
    assert isinstance(parser, argparse.ArgumentParser)


def test_run_with_filters_prints_json(monkeypatch, capsys) -> None:
    """_run with no --replies-json produces list_only output."""

    def fake_list_review_comments(*, runner, repo, pr_number):
        return _make_transformed_comments()

    monkeypatch.setattr(
        "scripts.github.triage_review_comments.list_review_comments",
        fake_list_review_comments,
    )

    stub_runner = QueueRunner([])
    namespace = argparse.Namespace(
        repo="octo/widgets",
        pr=5,
        author_substring="copilot",
        contains=None,
        path=None,
        replies_json=None,
    )
    exit_code = _run(namespace, _build_parser(), stub_runner)
    assert exit_code == 0

    output = json.loads(capsys.readouterr().out)
    assert output["action"] == "list_only"
    assert output["comments_count"] == 1
    assert output["repo"] == "octo/widgets"
    assert output["pr"] == 5


def test_run_with_replies_json(monkeypatch, capsys) -> None:
    """_run with --replies-json triggers reply+resolve flow."""

    def fake_list_review_comments(*, runner, repo, pr_number):
        return _make_transformed_comments()

    reply_calls: list[dict[str, Any]] = []

    def fake_post_reply(*, runner, repo, pr_number, comment_id, body):
        reply_calls.append({"comment_id": comment_id, "body": body})
        return {"id": 999, "node_id": "NODE999"}, False

    def fake_resolve(*, runner, repo, pr_number, comment_id):
        return True

    monkeypatch.setattr(
        "scripts.github.triage_review_comments.list_review_comments",
        fake_list_review_comments,
    )
    monkeypatch.setattr(
        "scripts.github.triage_review_comments.post_reply_idempotent",
        fake_post_reply,
    )
    monkeypatch.setattr(
        "scripts.github.triage_review_comments.resolve_review_thread",
        fake_resolve,
    )

    stub_runner = QueueRunner([])
    replies_json_str = json.dumps([{"comment_id": 100, "body": "Addressed."}])
    namespace = argparse.Namespace(
        repo="octo/widgets",
        pr=5,
        author_substring=None,
        contains=None,
        path=None,
        replies_json=replies_json_str,
    )
    exit_code = _run(namespace, _build_parser(), stub_runner)
    assert exit_code == 0

    output = json.loads(capsys.readouterr().out)
    assert output["action"] == "reply_and_resolve"
    assert len(output["reply_results"]) == 1
    assert output["reply_results"][0]["reply_id"] == 999
    assert reply_calls[0]["comment_id"] == 100


def test_run_auto_detects_repo_and_pr(monkeypatch, capsys) -> None:
    """_run falls back to current_repo and active_pr_number when args omit them."""

    def fake_list_review_comments(*, runner, repo, pr_number):
        return []

    monkeypatch.setattr(
        "scripts.github.triage_review_comments.list_review_comments",
        fake_list_review_comments,
    )
    monkeypatch.setattr(
        "scripts.github.triage_review_comments.current_repo",
        lambda runner: "auto/repo",
    )
    monkeypatch.setattr(
        "scripts.github.triage_review_comments.active_pr_number",
        lambda runner: 99,
    )

    stub_runner = QueueRunner([])
    namespace = argparse.Namespace(
        repo=None,
        pr=None,
        author_substring=None,
        contains=None,
        path=None,
        replies_json=None,
    )
    exit_code = _run(namespace, _build_parser(), stub_runner)
    assert exit_code == 0

    output = json.loads(capsys.readouterr().out)
    assert output["repo"] == "auto/repo"
    assert output["pr"] == 99


def test_build_parser_accepts_all_flags() -> None:
    parser = _build_parser()
    parsed = parser.parse_args(
        [
            "--repo",
            "owner/name",
            "--pr",
            "7",
            "--author-substring",
            "copilot",
            "--contains",
            "refactor",
            "--path",
            "src/main.py",
            "--replies-json",
            '[{"comment_id": 1, "body": "Done"}]',
        ]
    )
    assert parsed.repo == "owner/name"
    assert parsed.pr == 7
    assert parsed.author_substring == "copilot"
    assert parsed.contains == "refactor"
    assert parsed.path == "src/main.py"
    assert parsed.replies_json is not None


def test_main_delegates(monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.github.triage_review_comments.run_actionable_main",
        lambda **kwargs: 0,
    )
    assert main() == 0
