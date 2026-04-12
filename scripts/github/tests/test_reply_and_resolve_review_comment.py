"""Tests for reply_and_resolve_review_comment module."""

from __future__ import annotations

import argparse
import json

import pytest

from scripts.github.conftest import QueueRunner, as_stdout, make_call, make_runner
from scripts.github.gh_cli import GhCliError
from scripts.github.reply_and_resolve_review_comment import (
    _RESOLVE_MUTATION,
    _THREAD_QUERY,
    CommentContext,
    ResultArgs,
    _build_parser,
    _build_result,
    _emit_result,
    _end_cursor_if_has_next,
    _extract_review_threads_root,
    _extract_thread_id_for_comment,
    _find_thread_for_comment,
    _maybe_post_reply,
    _maybe_resolve_thread,
    _normalize_body,
    _post_reply_if_needed,
    _pr_number_from_url,
    _read_body,
    _resolve_body,
    _resolve_comment_context,
    _run,
    fetch_comment_context,
    find_existing_reply,
    main,
    post_reply,
    post_reply_idempotent,
    resolve_review_thread,
    resolve_review_thread_id,
)

_REPO = "octo/widgets"
_PR_NUMBER = 45
_COMMENT_ID = 999


# ---------------------------------------------------------------------------
# _read_body
# ---------------------------------------------------------------------------


def test_read_body_from_text() -> None:
    result = _read_body(body="hello", body_file=None)
    assert result == "hello"


def test_read_body_missing_raises() -> None:
    with pytest.raises(ValueError, match="Body is required"):
        _read_body(body=None, body_file=None)


# ---------------------------------------------------------------------------
# _pr_number_from_url
# ---------------------------------------------------------------------------


def test_pr_number_from_url_valid() -> None:
    url = "https://api.github.com/repos/octo/widgets/pulls/45"
    assert _pr_number_from_url(url) == 45


def test_pr_number_from_url_invalid() -> None:
    with pytest.raises(ValueError, match="Unable to parse PR number"):
        _pr_number_from_url("https://api.github.com/repos/octo/widgets/issues/45")


# ---------------------------------------------------------------------------
# fetch_comment_context
# ---------------------------------------------------------------------------


def _fetch_comment_argv(owner: str, name: str, comment_id: int) -> list[str]:
    return ["gh", "api", f"/repos/{owner}/{name}/pulls/comments/{comment_id}"]


def test_fetch_comment_context_success() -> None:
    payload = {
        "node_id": "PRR_abc",
        "pull_request_url": "https://api.github.com/repos/octo/widgets/pulls/45",
    }
    runner = make_runner(make_call(_fetch_comment_argv("octo", "widgets", _COMMENT_ID), payload))
    context = fetch_comment_context(runner=runner, repo=_REPO, comment_id=_COMMENT_ID)
    assert context == CommentContext(repo=_REPO, pr_number=_PR_NUMBER)
    runner.assert_exhausted()


def test_fetch_comment_context_non_dict() -> None:
    runner = make_runner(make_call(_fetch_comment_argv("octo", "widgets", _COMMENT_ID), [1, 2]))
    with pytest.raises(ValueError, match="Unexpected comment payload"):
        fetch_comment_context(runner=runner, repo=_REPO, comment_id=_COMMENT_ID)


def test_fetch_comment_context_missing_node_id() -> None:
    payload = {"pull_request_url": "https://api.github.com/repos/octo/widgets/pulls/45"}
    runner = make_runner(make_call(_fetch_comment_argv("octo", "widgets", _COMMENT_ID), payload))
    with pytest.raises(ValueError, match="Comment missing node_id"):
        fetch_comment_context(runner=runner, repo=_REPO, comment_id=_COMMENT_ID)


def test_fetch_comment_context_blank_node_id() -> None:
    payload = {
        "node_id": "   ",
        "pull_request_url": "https://api.github.com/repos/octo/widgets/pulls/45",
    }
    runner = make_runner(make_call(_fetch_comment_argv("octo", "widgets", _COMMENT_ID), payload))
    with pytest.raises(ValueError, match="Comment missing node_id"):
        fetch_comment_context(runner=runner, repo=_REPO, comment_id=_COMMENT_ID)


def test_fetch_comment_context_missing_pull_request_url() -> None:
    payload = {"node_id": "PRR_abc"}
    runner = make_runner(make_call(_fetch_comment_argv("octo", "widgets", _COMMENT_ID), payload))
    with pytest.raises(ValueError, match="Comment missing pull_request_url"):
        fetch_comment_context(runner=runner, repo=_REPO, comment_id=_COMMENT_ID)


def test_fetch_comment_context_blank_pull_request_url() -> None:
    payload = {"node_id": "PRR_abc", "pull_request_url": "  "}
    runner = make_runner(make_call(_fetch_comment_argv("octo", "widgets", _COMMENT_ID), payload))
    with pytest.raises(ValueError, match="Comment missing pull_request_url"):
        fetch_comment_context(runner=runner, repo=_REPO, comment_id=_COMMENT_ID)


# ---------------------------------------------------------------------------
# post_reply
# ---------------------------------------------------------------------------


def _post_reply_argv(comment_id: int, body: str) -> list[str]:
    return [
        "gh",
        "api",
        "--method",
        "POST",
        f"/repos/octo/widgets/pulls/{_PR_NUMBER}/comments",
        "-F",
        f"in_reply_to={comment_id}",
        "-f",
        f"body={body}",
    ]


def test_post_reply_success() -> None:
    reply_payload = {"id": 555, "node_id": "NODE555"}
    runner = make_runner(make_call(_post_reply_argv(_COMMENT_ID, "Fix applied"), reply_payload))
    result = post_reply(runner=runner, repo=_REPO, pr_number=_PR_NUMBER, comment_id=_COMMENT_ID, body="Fix applied")
    assert result == reply_payload
    runner.assert_exhausted()


def test_post_reply_non_dict_raises() -> None:
    runner = make_runner(make_call(_post_reply_argv(_COMMENT_ID, "Fix"), as_stdout(["a list"])))
    with pytest.raises(ValueError, match="Unexpected reply payload"):
        post_reply(runner=runner, repo=_REPO, pr_number=_PR_NUMBER, comment_id=_COMMENT_ID, body="Fix")


# ---------------------------------------------------------------------------
# _normalize_body
# ---------------------------------------------------------------------------


def test_normalize_body_strips_lines() -> None:
    assert _normalize_body("  hello  \n  world  ") == "hello\n  world"


# ---------------------------------------------------------------------------
# find_existing_reply
# ---------------------------------------------------------------------------


def _list_comments_argv() -> list[str]:
    return ["gh", "api", f"/repos/octo/widgets/pulls/{_PR_NUMBER}/comments", "--paginate"]


def test_find_existing_reply_found() -> None:
    existing_comment = {
        "in_reply_to": _COMMENT_ID,
        "user": {"login": "bot-user"},
        "body": "Fix applied",
    }
    runner = make_runner(make_call(_list_comments_argv(), [existing_comment]))
    result = find_existing_reply(
        runner=runner,
        repo=_REPO,
        pr_number=_PR_NUMBER,
        comment_id=_COMMENT_ID,
        body="Fix applied",
        author="bot-user",
    )
    assert result == existing_comment


def test_find_existing_reply_no_match() -> None:
    other_comment = {
        "in_reply_to": _COMMENT_ID,
        "user": {"login": "bot-user"},
        "body": "Different text",
    }
    runner = make_runner(make_call(_list_comments_argv(), [other_comment]))
    result = find_existing_reply(
        runner=runner,
        repo=_REPO,
        pr_number=_PR_NUMBER,
        comment_id=_COMMENT_ID,
        body="Fix applied",
        author="bot-user",
    )
    assert result is None


def test_find_existing_reply_non_list_raises() -> None:
    runner = make_runner(make_call(_list_comments_argv(), {"not": "a list"}))
    with pytest.raises(ValueError, match="Unexpected PR review comments payload"):
        find_existing_reply(
            runner=runner,
            repo=_REPO,
            pr_number=_PR_NUMBER,
            comment_id=_COMMENT_ID,
            body="Fix",
            author="bot-user",
        )


def test_find_existing_reply_non_dict_item_skipped() -> None:
    runner = make_runner(make_call(_list_comments_argv(), ["not-a-dict"]))
    result = find_existing_reply(
        runner=runner,
        repo=_REPO,
        pr_number=_PR_NUMBER,
        comment_id=_COMMENT_ID,
        body="Fix",
        author="bot-user",
    )
    assert result is None


def test_find_existing_reply_wrong_in_reply_to() -> None:
    comment = {"in_reply_to": 12345, "user": {"login": "bot-user"}, "body": "Fix"}
    runner = make_runner(make_call(_list_comments_argv(), [comment]))
    result = find_existing_reply(
        runner=runner,
        repo=_REPO,
        pr_number=_PR_NUMBER,
        comment_id=_COMMENT_ID,
        body="Fix",
        author="bot-user",
    )
    assert result is None


def test_find_existing_reply_wrong_author() -> None:
    comment = {"in_reply_to": _COMMENT_ID, "user": {"login": "other-user"}, "body": "Fix"}
    runner = make_runner(make_call(_list_comments_argv(), [comment]))
    result = find_existing_reply(
        runner=runner,
        repo=_REPO,
        pr_number=_PR_NUMBER,
        comment_id=_COMMENT_ID,
        body="Fix",
        author="bot-user",
    )
    assert result is None


def test_find_existing_reply_non_string_body_skipped() -> None:
    comment = {"in_reply_to": _COMMENT_ID, "user": {"login": "bot-user"}, "body": 42}
    runner = make_runner(make_call(_list_comments_argv(), [comment]))
    result = find_existing_reply(
        runner=runner,
        repo=_REPO,
        pr_number=_PR_NUMBER,
        comment_id=_COMMENT_ID,
        body="Fix",
        author="bot-user",
    )
    assert result is None


# ---------------------------------------------------------------------------
# post_reply_idempotent
# ---------------------------------------------------------------------------


def _login_argv() -> list[str]:
    return ["gh", "api", "/user"]


def test_post_reply_idempotent_existing_skipped() -> None:
    existing_comment = {
        "in_reply_to": _COMMENT_ID,
        "user": {"login": "bot-user"},
        "body": "Fix applied",
    }
    runner = make_runner(
        make_call(_login_argv(), {"login": "bot-user"}),
        make_call(_list_comments_argv(), [existing_comment]),
    )
    reply, skipped = post_reply_idempotent(
        runner=runner, repo=_REPO, pr_number=_PR_NUMBER, comment_id=_COMMENT_ID, body="Fix applied"
    )
    assert reply == existing_comment
    assert skipped is True
    runner.assert_exhausted()


def test_post_reply_idempotent_new_posted() -> None:
    new_reply = {"id": 555, "node_id": "NODE555"}
    runner = make_runner(
        make_call(_login_argv(), {"login": "bot-user"}),
        make_call(_list_comments_argv(), []),
        make_call(_post_reply_argv(_COMMENT_ID, "Fix applied"), new_reply),
    )
    reply, skipped = post_reply_idempotent(
        runner=runner, repo=_REPO, pr_number=_PR_NUMBER, comment_id=_COMMENT_ID, body="Fix applied"
    )
    assert reply == new_reply
    assert skipped is False
    runner.assert_exhausted()


# ---------------------------------------------------------------------------
# _end_cursor_if_has_next
# ---------------------------------------------------------------------------


def test_end_cursor_no_next_page() -> None:
    assert _end_cursor_if_has_next({"hasNextPage": False, "endCursor": "abc"}) is None


def test_end_cursor_has_next_page() -> None:
    assert _end_cursor_if_has_next({"hasNextPage": True, "endCursor": "abc"}) == "abc"


def test_end_cursor_empty_cursor() -> None:
    assert _end_cursor_if_has_next({"hasNextPage": True, "endCursor": "  "}) is None


def test_end_cursor_not_dict() -> None:
    assert _end_cursor_if_has_next("not-a-dict") is None


def test_end_cursor_none_cursor() -> None:
    assert _end_cursor_if_has_next({"hasNextPage": True, "endCursor": None}) is None


# ---------------------------------------------------------------------------
# _extract_review_threads_root
# ---------------------------------------------------------------------------


def _make_graphql_threads_response(thread_nodes: list, page_info: dict | None = None) -> dict:
    if page_info is None:
        page_info = {"hasNextPage": False, "endCursor": None}
    return {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": thread_nodes,
                        "pageInfo": page_info,
                    }
                }
            }
        }
    }


def test_extract_review_threads_root_valid() -> None:
    response = _make_graphql_threads_response([])
    result = _extract_review_threads_root(response)
    assert "nodes" in result
    assert "pageInfo" in result


def test_extract_review_threads_root_not_dict() -> None:
    with pytest.raises(ValueError, match="Unexpected GraphQL response"):
        _extract_review_threads_root("not-dict")


def test_extract_review_threads_root_missing_data() -> None:
    with pytest.raises(ValueError, match="Unexpected GraphQL response"):
        _extract_review_threads_root({"data": "not-dict"})


def test_extract_review_threads_root_missing_repository() -> None:
    with pytest.raises(ValueError, match="Unexpected GraphQL response"):
        _extract_review_threads_root({"data": {"repository": "not-dict"}})


def test_extract_review_threads_root_missing_pull_request() -> None:
    with pytest.raises(ValueError, match="Unexpected GraphQL response"):
        _extract_review_threads_root({"data": {"repository": {"pullRequest": "not-dict"}}})


def test_extract_review_threads_root_missing_review_threads() -> None:
    with pytest.raises(ValueError, match="Unexpected GraphQL response"):
        _extract_review_threads_root({"data": {"repository": {"pullRequest": {"reviewThreads": 42}}}})


# ---------------------------------------------------------------------------
# _find_thread_for_comment
# ---------------------------------------------------------------------------


def _make_thread_node(thread_id: str, is_resolved: bool, comment_db_ids: list[int]) -> dict:
    return {
        "id": thread_id,
        "isResolved": is_resolved,
        "comments": {"nodes": [{"databaseId": cid} for cid in comment_db_ids]},
    }


def test_find_thread_for_comment_found() -> None:
    thread_node = _make_thread_node("TID_1", False, [_COMMENT_ID])
    result = _find_thread_for_comment(thread_nodes=[thread_node], comment_id=_COMMENT_ID)
    assert result == ("TID_1", False)


def test_find_thread_for_comment_not_found() -> None:
    thread_node = _make_thread_node("TID_1", False, [111])
    result = _find_thread_for_comment(thread_nodes=[thread_node], comment_id=_COMMENT_ID)
    assert result is None


def test_find_thread_for_comment_non_list() -> None:
    result = _find_thread_for_comment(thread_nodes="not-a-list", comment_id=_COMMENT_ID)
    assert result is None


def test_find_thread_for_comment_non_dict_node() -> None:
    result = _find_thread_for_comment(thread_nodes=["not-a-dict"], comment_id=_COMMENT_ID)
    assert result is None


def test_find_thread_for_comment_missing_thread_id() -> None:
    node_without_id = {"comments": {"nodes": [{"databaseId": _COMMENT_ID}]}}
    result = _find_thread_for_comment(thread_nodes=[node_without_id], comment_id=_COMMENT_ID)
    assert result is None


def test_find_thread_for_comment_blank_thread_id() -> None:
    node_blank_id = {"id": "  ", "comments": {"nodes": [{"databaseId": _COMMENT_ID}]}}
    result = _find_thread_for_comment(thread_nodes=[node_blank_id], comment_id=_COMMENT_ID)
    assert result is None


def test_find_thread_for_comment_comments_not_dict() -> None:
    node_no_comments = {"id": "TID_1", "isResolved": False, "comments": "not-a-dict"}
    result = _find_thread_for_comment(thread_nodes=[node_no_comments], comment_id=_COMMENT_ID)
    assert result is None


# ---------------------------------------------------------------------------
# _extract_thread_id_for_comment (pagination)
# ---------------------------------------------------------------------------


def _graphql_query_argv(after: str | None = None) -> list[str]:
    argv = [
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
        f"number={_PR_NUMBER}",
    ]
    if after is not None:
        argv.extend(["-f", f"after={after}"])
    return argv


def test_extract_thread_id_found_first_page() -> None:
    thread_node = _make_thread_node("TID_1", False, [_COMMENT_ID])
    response = _make_graphql_threads_response([thread_node])
    runner = make_runner(make_call(_graphql_query_argv(), response))
    thread_id, is_resolved = _extract_thread_id_for_comment(
        runner=runner, repo=_REPO, pr_number=_PR_NUMBER, comment_id=_COMMENT_ID
    )
    assert thread_id == "TID_1"
    assert is_resolved is False
    runner.assert_exhausted()


def test_extract_thread_id_found_second_page() -> None:
    page_one_response = _make_graphql_threads_response(
        [_make_thread_node("TID_X", False, [111])],
        page_info={"hasNextPage": True, "endCursor": "cursor_abc"},
    )
    page_two_response = _make_graphql_threads_response([_make_thread_node("TID_2", True, [_COMMENT_ID])])
    runner = make_runner(
        make_call(_graphql_query_argv(), page_one_response),
        make_call(_graphql_query_argv(after="cursor_abc"), page_two_response),
    )
    thread_id, is_resolved = _extract_thread_id_for_comment(
        runner=runner, repo=_REPO, pr_number=_PR_NUMBER, comment_id=_COMMENT_ID
    )
    assert thread_id == "TID_2"
    assert is_resolved is True
    runner.assert_exhausted()


def test_extract_thread_id_not_found_raises() -> None:
    response = _make_graphql_threads_response([_make_thread_node("TID_X", False, [111])])
    runner = make_runner(make_call(_graphql_query_argv(), response))
    with pytest.raises(ValueError, match="Unable to locate review thread"):
        _extract_thread_id_for_comment(runner=runner, repo=_REPO, pr_number=_PR_NUMBER, comment_id=_COMMENT_ID)


# ---------------------------------------------------------------------------
# resolve_review_thread
# ---------------------------------------------------------------------------


def _resolve_mutation_argv(thread_id: str) -> list[str]:
    return [
        "gh",
        "api",
        "graphql",
        "-f",
        f"query={_RESOLVE_MUTATION}",
        "-f",
        f"threadId={thread_id}",
    ]


def test_resolve_review_thread_already_resolved() -> None:
    thread_node = _make_thread_node("TID_1", True, [_COMMENT_ID])
    response = _make_graphql_threads_response([thread_node])
    runner = make_runner(make_call(_graphql_query_argv(), response))
    result = resolve_review_thread(runner=runner, repo=_REPO, pr_number=_PR_NUMBER, comment_id=_COMMENT_ID)
    assert result is True
    runner.assert_exhausted()


def test_resolve_review_thread_needs_resolving() -> None:
    thread_node = _make_thread_node("TID_1", False, [_COMMENT_ID])
    graphql_response = _make_graphql_threads_response([thread_node])
    mutation_response = {"data": {"resolveReviewThread": {"thread": {"id": "TID_1", "isResolved": True}}}}
    runner = make_runner(
        make_call(_graphql_query_argv(), graphql_response),
        make_call(_resolve_mutation_argv("TID_1"), mutation_response),
    )
    result = resolve_review_thread(runner=runner, repo=_REPO, pr_number=_PR_NUMBER, comment_id=_COMMENT_ID)
    assert result is True
    runner.assert_exhausted()


# ---------------------------------------------------------------------------
# resolve_review_thread_id
# ---------------------------------------------------------------------------


def test_resolve_review_thread_id_success() -> None:
    mutation_response = {"data": {"resolveReviewThread": {"thread": {"id": "TID_1", "isResolved": True}}}}
    runner = make_runner(make_call(_resolve_mutation_argv("TID_1"), mutation_response))
    result = resolve_review_thread_id(runner=runner, thread_id="TID_1")
    assert result is True
    runner.assert_exhausted()


def test_resolve_review_thread_id_empty_raises() -> None:
    with pytest.raises(ValueError, match="thread_id is required"):
        resolve_review_thread_id(runner=make_runner(), thread_id="  ")


def test_resolve_review_thread_id_non_dict_raises() -> None:
    runner = make_runner(make_call(_resolve_mutation_argv("TID_1"), as_stdout(["a list"])))
    with pytest.raises(ValueError, match="Unexpected GraphQL mutation response"):
        resolve_review_thread_id(runner=runner, thread_id="TID_1")


# ---------------------------------------------------------------------------
# _resolve_body
# ---------------------------------------------------------------------------


def test_resolve_body_resolve_only_returns_none() -> None:
    args = argparse.Namespace(resolve_only=True, body="ignored", body_file=None)
    assert _resolve_body(args) is None


def test_resolve_body_normal_returns_body() -> None:
    args = argparse.Namespace(resolve_only=False, body="Fix applied", body_file=None)
    assert _resolve_body(args) == "Fix applied"


# ---------------------------------------------------------------------------
# _resolve_comment_context
# ---------------------------------------------------------------------------


def test_resolve_comment_context_with_pr_arg() -> None:
    args = argparse.Namespace(repo=_REPO, pr=_PR_NUMBER, comment_id=_COMMENT_ID)
    runner = make_runner()
    context = _resolve_comment_context(runner=runner, args=args)
    assert context == CommentContext(repo=_REPO, pr_number=_PR_NUMBER)
    runner.assert_exhausted()


def test_resolve_comment_context_without_pr_arg() -> None:
    payload = {
        "node_id": "PRR_abc",
        "pull_request_url": "https://api.github.com/repos/octo/widgets/pulls/45",
    }
    args = argparse.Namespace(repo=_REPO, pr=None, comment_id=_COMMENT_ID)
    runner = make_runner(make_call(_fetch_comment_argv("octo", "widgets", _COMMENT_ID), payload))
    context = _resolve_comment_context(runner=runner, args=args)
    assert context == CommentContext(repo=_REPO, pr_number=_PR_NUMBER)
    runner.assert_exhausted()


# ---------------------------------------------------------------------------
# _maybe_post_reply
# ---------------------------------------------------------------------------


def test_maybe_post_reply_none_body() -> None:
    runner = make_runner()
    result = _maybe_post_reply(
        runner=runner,
        ctx=CommentContext(repo=_REPO, pr_number=_PR_NUMBER),
        comment_id=_COMMENT_ID,
        body=None,
    )
    assert result is None
    runner.assert_exhausted()


def test_maybe_post_reply_with_body() -> None:
    new_reply = {"id": 555, "node_id": "NODE555"}
    runner = make_runner(
        make_call(_login_argv(), {"login": "bot-user"}),
        make_call(_list_comments_argv(), []),
        make_call(_post_reply_argv(_COMMENT_ID, "Fix"), new_reply),
    )
    result = _maybe_post_reply(
        runner=runner,
        ctx=CommentContext(repo=_REPO, pr_number=_PR_NUMBER),
        comment_id=_COMMENT_ID,
        body="Fix",
    )
    assert result == new_reply
    runner.assert_exhausted()


# ---------------------------------------------------------------------------
# _post_reply_if_needed
# ---------------------------------------------------------------------------


def test_post_reply_if_needed_none_body() -> None:
    runner = make_runner()
    reply, skipped = _post_reply_if_needed(
        runner=runner,
        ctx=CommentContext(repo=_REPO, pr_number=_PR_NUMBER),
        comment_id=_COMMENT_ID,
        body=None,
    )
    assert reply is None
    assert skipped is None
    runner.assert_exhausted()


def test_post_reply_if_needed_with_body() -> None:
    new_reply = {"id": 555, "node_id": "NODE555"}
    runner = make_runner(
        make_call(_login_argv(), {"login": "bot-user"}),
        make_call(_list_comments_argv(), []),
        make_call(_post_reply_argv(_COMMENT_ID, "Fix"), new_reply),
    )
    reply, skipped = _post_reply_if_needed(
        runner=runner,
        ctx=CommentContext(repo=_REPO, pr_number=_PR_NUMBER),
        comment_id=_COMMENT_ID,
        body="Fix",
    )
    assert reply == new_reply
    assert skipped is False
    runner.assert_exhausted()


# ---------------------------------------------------------------------------
# _maybe_resolve_thread
# ---------------------------------------------------------------------------


def test_maybe_resolve_thread_no_resolve() -> None:
    runner = make_runner()
    result = _maybe_resolve_thread(
        runner=runner,
        ctx=CommentContext(repo=_REPO, pr_number=_PR_NUMBER),
        comment_id=_COMMENT_ID,
        no_resolve=True,
        thread_id=None,
    )
    assert result is None
    runner.assert_exhausted()


def test_maybe_resolve_thread_with_thread_id() -> None:
    mutation_response = {"data": {"resolveReviewThread": {"thread": {"id": "TID_1", "isResolved": True}}}}
    runner = make_runner(make_call(_resolve_mutation_argv("TID_1"), mutation_response))
    result = _maybe_resolve_thread(
        runner=runner,
        ctx=CommentContext(repo=_REPO, pr_number=_PR_NUMBER),
        comment_id=_COMMENT_ID,
        no_resolve=False,
        thread_id="TID_1",
    )
    assert result is True
    runner.assert_exhausted()


def test_maybe_resolve_thread_without_thread_id() -> None:
    thread_node = _make_thread_node("TID_1", True, [_COMMENT_ID])
    response = _make_graphql_threads_response([thread_node])
    runner = make_runner(make_call(_graphql_query_argv(), response))
    result = _maybe_resolve_thread(
        runner=runner,
        ctx=CommentContext(repo=_REPO, pr_number=_PR_NUMBER),
        comment_id=_COMMENT_ID,
        no_resolve=False,
        thread_id=None,
    )
    assert result is True
    runner.assert_exhausted()


# ---------------------------------------------------------------------------
# _build_result
# ---------------------------------------------------------------------------


def test_build_result_full() -> None:
    reply = {"id": 555, "node_id": "NODE555"}
    result = _build_result(
        ctx=CommentContext(repo=_REPO, pr_number=_PR_NUMBER),
        args=ResultArgs(comment_id=_COMMENT_ID, thread_id="TID_1"),
        reply=reply,
        reply_skipped=False,
        resolved=True,
    )
    assert result == {
        "repo": _REPO,
        "pr": _PR_NUMBER,
        "in_reply_to": _COMMENT_ID,
        "thread_id": "TID_1",
        "reply_id": 555,
        "reply_node_id": "NODE555",
        "reply_skipped": False,
        "resolved": True,
    }


def test_build_result_no_reply() -> None:
    result = _build_result(
        ctx=CommentContext(repo=_REPO, pr_number=_PR_NUMBER),
        args=ResultArgs(comment_id=_COMMENT_ID, thread_id=None),
        reply=None,
        reply_skipped=None,
        resolved=None,
    )
    assert result["reply_id"] is None
    assert result["reply_node_id"] is None
    assert result["reply_skipped"] is None
    assert result["resolved"] is None
    assert result["thread_id"] is None


# ---------------------------------------------------------------------------
# _emit_result
# ---------------------------------------------------------------------------


def test_emit_result_json_mode(capsys: pytest.CaptureFixture[str]) -> None:
    args = argparse.Namespace(json=True, comment_id=_COMMENT_ID)
    result = {"pr": _PR_NUMBER, "resolved": True}
    _emit_result(args=args, result=result)
    output = json.loads(capsys.readouterr().out)
    assert output["pr"] == _PR_NUMBER


def test_emit_result_text_resolved_true(capsys: pytest.CaptureFixture[str]) -> None:
    args = argparse.Namespace(json=False, comment_id=_COMMENT_ID)
    result = {"pr": _PR_NUMBER, "resolved": True}
    _emit_result(args=args, result=result)
    captured = capsys.readouterr().out
    assert f"comment {_COMMENT_ID}" in captured
    assert "Resolved review thread." in captured


def test_emit_result_text_resolved_false(capsys: pytest.CaptureFixture[str]) -> None:
    args = argparse.Namespace(json=False, comment_id=_COMMENT_ID)
    result = {"pr": _PR_NUMBER, "resolved": False}
    _emit_result(args=args, result=result)
    captured = capsys.readouterr().out
    assert "not resolved" in captured


def test_emit_result_text_resolved_none(capsys: pytest.CaptureFixture[str]) -> None:
    args = argparse.Namespace(json=False, comment_id=_COMMENT_ID)
    result = {"pr": _PR_NUMBER, "resolved": None}
    _emit_result(args=args, result=result)
    captured = capsys.readouterr().out
    assert "Resolved" not in captured
    assert "not resolved" not in captured


# ---------------------------------------------------------------------------
# _run (orchestrator)
# ---------------------------------------------------------------------------


def test_run_full_flow() -> None:
    reply_payload = {"id": 555, "node_id": "NODE555"}
    thread_node = _make_thread_node("TID_1", False, [_COMMENT_ID])
    graphql_response = _make_graphql_threads_response([thread_node])
    mutation_response = {"data": {"resolveReviewThread": {"thread": {"id": "TID_1", "isResolved": True}}}}

    runner = make_runner(
        # post_reply_idempotent: current_login
        make_call(_login_argv(), {"login": "bot-user"}),
        # post_reply_idempotent: find_existing_reply
        make_call(_list_comments_argv(), []),
        # post_reply_idempotent: post_reply
        make_call(_post_reply_argv(_COMMENT_ID, "Fix applied"), reply_payload),
        # resolve_review_thread: _fetch_review_threads_page
        make_call(_graphql_query_argv(), graphql_response),
        # resolve_review_thread: resolve mutation
        make_call(_resolve_mutation_argv("TID_1"), mutation_response),
    )

    args = argparse.Namespace(
        repo=_REPO,
        pr=_PR_NUMBER,
        comment_id=_COMMENT_ID,
        body="Fix applied",
        body_file=None,
        resolve_only=False,
        no_resolve=False,
        thread_id=None,
        json=False,
    )
    result = _run(args, runner=runner)
    assert result["reply_id"] == 555
    assert result["resolved"] is True
    runner.assert_exhausted()


def test_run_resolve_only_flow() -> None:
    thread_node = _make_thread_node("TID_1", True, [_COMMENT_ID])
    graphql_response = _make_graphql_threads_response([thread_node])

    runner = make_runner(
        make_call(_graphql_query_argv(), graphql_response),
    )

    args = argparse.Namespace(
        repo=_REPO,
        pr=_PR_NUMBER,
        comment_id=_COMMENT_ID,
        body=None,
        body_file=None,
        resolve_only=True,
        no_resolve=False,
        thread_id=None,
        json=False,
    )
    result = _run(args, runner=runner)
    assert result["reply_id"] is None
    assert result["resolved"] is True
    runner.assert_exhausted()


def test_run_no_resolve_flow() -> None:
    reply_payload = {"id": 555, "node_id": "NODE555"}

    runner = make_runner(
        make_call(_login_argv(), {"login": "bot-user"}),
        make_call(_list_comments_argv(), []),
        make_call(_post_reply_argv(_COMMENT_ID, "Noted"), reply_payload),
    )

    args = argparse.Namespace(
        repo=_REPO,
        pr=_PR_NUMBER,
        comment_id=_COMMENT_ID,
        body="Noted",
        body_file=None,
        resolve_only=False,
        no_resolve=True,
        thread_id=None,
        json=False,
    )
    result = _run(args, runner=runner)
    assert result["reply_id"] == 555
    assert result["resolved"] is None
    runner.assert_exhausted()


def test_run_with_thread_id() -> None:
    reply_payload = {"id": 555, "node_id": "NODE555"}
    mutation_response = {"data": {"resolveReviewThread": {"thread": {"id": "TID_DIRECT", "isResolved": True}}}}

    runner = make_runner(
        make_call(_login_argv(), {"login": "bot-user"}),
        make_call(_list_comments_argv(), []),
        make_call(_post_reply_argv(_COMMENT_ID, "Done"), reply_payload),
        make_call(_resolve_mutation_argv("TID_DIRECT"), mutation_response),
    )

    args = argparse.Namespace(
        repo=_REPO,
        pr=_PR_NUMBER,
        comment_id=_COMMENT_ID,
        body="Done",
        body_file=None,
        resolve_only=False,
        no_resolve=False,
        thread_id="TID_DIRECT",
        json=False,
    )
    result = _run(args, runner=runner)
    assert result["thread_id"] == "TID_DIRECT"
    assert result["resolved"] is True
    runner.assert_exhausted()


# ---------------------------------------------------------------------------
# _build_parser
# ---------------------------------------------------------------------------


def test_build_parser_returns_parser() -> None:
    parser = _build_parser()
    assert isinstance(parser, argparse.ArgumentParser)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def test_main_success(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    reply_payload = {"id": 555, "node_id": "NODE555"}
    thread_node = _make_thread_node("TID_1", True, [_COMMENT_ID])
    graphql_response = _make_graphql_threads_response([thread_node])

    call_queue = [
        make_call(_login_argv(), {"login": "bot-user"}),
        make_call(_list_comments_argv(), []),
        make_call(_post_reply_argv(_COMMENT_ID, "Fix"), reply_payload),
        make_call(_graphql_query_argv(), graphql_response),
    ]
    queue_runner = QueueRunner(call_queue)

    monkeypatch.setattr(
        "scripts.github.reply_and_resolve_review_comment.SubprocessGhRunner",
        lambda: queue_runner,
    )
    monkeypatch.setattr(
        "sys.argv",
        ["prog", "--repo", _REPO, "--comment-id", str(_COMMENT_ID), "--pr", str(_PR_NUMBER), "--body", "Fix"],
    )
    exit_code = main()
    assert exit_code == 0
    queue_runner.assert_exhausted()


def test_main_gh_cli_error_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def raise_error() -> QueueRunner:
        msg = "gh failed"
        raise GhCliError(msg, argv=["gh"], returncode=1, stdout="", stderr="oops")

    monkeypatch.setattr(
        "scripts.github.reply_and_resolve_review_comment.SubprocessGhRunner",
        raise_error,
    )
    monkeypatch.setattr(
        "sys.argv",
        ["prog", "--repo", _REPO, "--comment-id", str(_COMMENT_ID), "--body", "Fix", "--json"],
    )
    exit_code = main()
    assert exit_code == 2
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "error"


def test_main_gh_cli_error_text(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_error() -> QueueRunner:
        msg = "gh failed"
        raise GhCliError(msg, argv=["gh"], returncode=1, stdout="", stderr="oops")

    monkeypatch.setattr(
        "scripts.github.reply_and_resolve_review_comment.SubprocessGhRunner",
        raise_error,
    )
    monkeypatch.setattr(
        "sys.argv",
        ["prog", "--repo", _REPO, "--comment-id", str(_COMMENT_ID), "--body", "Fix"],
    )
    exit_code = main()
    assert exit_code == 2
