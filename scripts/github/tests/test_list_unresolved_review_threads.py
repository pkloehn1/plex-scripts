"""Tests for list_unresolved_review_threads module."""

from __future__ import annotations

import argparse
import json

import pytest

from scripts.github.conftest import ExpectedCall, QueueRunner
from scripts.github.gh_cli import GhCliError
from scripts.github.list_unresolved_review_threads import (
    _QUERY,
    ReviewComment,
    ReviewThread,
    _build_parser,
    _end_cursor_if_has_next,
    _parse_comment_node,
    _parse_thread_node,
    _parse_threads,
    _thread_contains_text,
    _thread_has_author,
    _thread_matches_filters,
    _thread_matches_path,
    filter_review_threads,
    list_unresolved_review_threads,
    main,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _graphql_argv(
    owner: str = "o",
    name: str = "n",
    pr_number: int = 42,
    after: str | None = None,
) -> list[str]:
    argv = [
        "gh",
        "api",
        "graphql",
        "-f",
        f"query={_QUERY}",
        "-f",
        f"owner={owner}",
        "-f",
        f"name={name}",
        "-F",
        f"number={pr_number}",
    ]
    if after is not None:
        argv.extend(["-f", f"after={after}"])
    return argv


def _comment_node(
    database_id: object = 100,
    node_id: object = "COMMENT_NODE_1",
    body: object = "fix this",
    url: object = "https://github.com/o/n/pull/42#comment-100",
    author_login: object = "alice",
) -> dict:
    author = {"login": author_login} if author_login is not None else None
    return {
        "databaseId": database_id,
        "id": node_id,
        "body": body,
        "url": url,
        "author": author,
    }


def _thread_node(
    thread_id: object = "THREAD_1",
    is_resolved: bool = False,
    path: object = "src/app.py",
    line: object = 10,
    comment_nodes: list | None = None,
) -> dict:
    if comment_nodes is None:
        comment_nodes = [_comment_node()]
    return {
        "id": thread_id,
        "isResolved": is_resolved,
        "path": path,
        "line": line,
        "comments": {"nodes": comment_nodes},
    }


def _graphql_response(
    thread_nodes: list | None = None,
    has_next_page: bool = False,
    end_cursor: object = None,
) -> dict:
    if thread_nodes is None:
        thread_nodes = [_thread_node()]
    return {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": thread_nodes,
                        "pageInfo": {
                            "hasNextPage": has_next_page,
                            "endCursor": end_cursor,
                        },
                    }
                }
            }
        }
    }


def _make_thread(
    thread_id: str = "T1",
    path: str | None = "src/app.py",
    line: int | None = 10,
    is_resolved: bool = False,
    comments: list[ReviewComment] | None = None,
) -> ReviewThread:
    if comments is None:
        comments = [
            ReviewComment(
                database_id=100,
                node_id="C1",
                author="alice",
                body="fix this",
                url="https://example.com",
            )
        ]
    return ReviewThread(
        thread_id=thread_id,
        path=path,
        line=line,
        is_resolved=is_resolved,
        comments=comments,
    )


# ---------------------------------------------------------------------------
# _parse_comment_node
# ---------------------------------------------------------------------------


class TestParseCommentNode:
    def test_valid_comment(self) -> None:
        result = _parse_comment_node(_comment_node())
        assert result is not None
        assert result.database_id == 100
        assert result.node_id == "COMMENT_NODE_1"
        assert result.author == "alice"
        assert result.body == "fix this"
        assert result.url == "https://github.com/o/n/pull/42#comment-100"

    def test_non_dict_returns_none(self) -> None:
        assert _parse_comment_node("not a dict") is None
        assert _parse_comment_node(None) is None

    def test_missing_database_id_returns_none(self) -> None:
        node = _comment_node()
        del node["databaseId"]
        assert _parse_comment_node(node) is None

    def test_non_int_database_id_returns_none(self) -> None:
        assert _parse_comment_node(_comment_node(database_id="bad")) is None

    def test_non_string_node_id_returns_none(self) -> None:
        assert _parse_comment_node(_comment_node(node_id=999)) is None

    def test_missing_author_yields_none_author(self) -> None:
        result = _parse_comment_node(_comment_node(author_login=None))
        assert result is not None
        assert result.author is None

    def test_non_string_body_defaults_to_empty(self) -> None:
        result = _parse_comment_node(_comment_node(body=42))
        assert result is not None
        assert result.body == ""

    def test_non_string_url_defaults_to_empty(self) -> None:
        result = _parse_comment_node(_comment_node(url=None))
        assert result is not None
        assert result.url == ""


# ---------------------------------------------------------------------------
# _parse_thread_node
# ---------------------------------------------------------------------------


class TestParseThreadNode:
    def test_valid_thread(self) -> None:
        result = _parse_thread_node(_thread_node())
        assert result is not None
        assert result.thread_id == "THREAD_1"
        assert result.path == "src/app.py"
        assert result.line == 10
        assert result.is_resolved is False
        assert len(result.comments) == 1

    def test_missing_thread_id_returns_none(self) -> None:
        node = _thread_node()
        del node["id"]
        assert _parse_thread_node(node) is None

    def test_non_string_thread_id_returns_none(self) -> None:
        assert _parse_thread_node(_thread_node(thread_id=123)) is None

    def test_non_string_path_yields_none(self) -> None:
        result = _parse_thread_node(_thread_node(path=42))
        assert result is not None
        assert result.path is None

    def test_non_int_line_yields_none(self) -> None:
        result = _parse_thread_node(_thread_node(line="bad"))
        assert result is not None
        assert result.line is None


# ---------------------------------------------------------------------------
# _end_cursor_if_has_next
# ---------------------------------------------------------------------------


class TestEndCursorIfHasNext:
    def test_no_next_page(self) -> None:
        assert _end_cursor_if_has_next({"hasNextPage": False, "endCursor": "abc"}) is None

    def test_has_next_page_with_cursor(self) -> None:
        assert _end_cursor_if_has_next({"hasNextPage": True, "endCursor": "cursor123"}) == "cursor123"

    def test_has_next_page_empty_cursor(self) -> None:
        assert _end_cursor_if_has_next({"hasNextPage": True, "endCursor": ""}) is None

    def test_has_next_page_non_string_cursor(self) -> None:
        assert _end_cursor_if_has_next({"hasNextPage": True, "endCursor": None}) is None

    def test_non_dict_returns_none(self) -> None:
        assert _end_cursor_if_has_next("bad") is None


# ---------------------------------------------------------------------------
# _parse_threads
# ---------------------------------------------------------------------------


class TestParseThreads:
    def test_valid_payload(self) -> None:
        payload = _graphql_response()
        threads, cursor = _parse_threads(payload)
        assert len(threads) == 1
        assert threads[0].thread_id == "THREAD_1"
        assert cursor is None

    def test_empty_nodes(self) -> None:
        payload = _graphql_response(thread_nodes=[])
        threads, cursor = _parse_threads(payload)
        assert threads == []
        assert cursor is None

    def test_with_pagination_cursor(self) -> None:
        payload = _graphql_response(has_next_page=True, end_cursor="next_page")
        threads, cursor = _parse_threads(payload)
        assert len(threads) == 1
        assert cursor == "next_page"

    def test_skips_invalid_thread_nodes(self) -> None:
        payload = _graphql_response(thread_nodes=[_thread_node(), _thread_node(thread_id=None)])
        threads, _ = _parse_threads(payload)
        assert len(threads) == 1


# ---------------------------------------------------------------------------
# list_unresolved_review_threads
# ---------------------------------------------------------------------------


class TestListUnresolvedReviewThreads:
    def test_returns_unresolved_only(self) -> None:
        response = _graphql_response(
            thread_nodes=[
                _thread_node(thread_id="UNRESOLVED", is_resolved=False),
                _thread_node(thread_id="RESOLVED", is_resolved=True),
            ]
        )
        runner = QueueRunner([ExpectedCall(argv=_graphql_argv(), stdout=json.dumps(response))])
        result = list_unresolved_review_threads(repo="o/n", pr_number=42, runner=runner)
        assert len(result) == 1
        assert result[0].thread_id == "UNRESOLVED"
        runner.assert_exhausted()

    def test_pagination_two_pages(self) -> None:
        page_one = _graphql_response(
            thread_nodes=[_thread_node(thread_id="T1")],
            has_next_page=True,
            end_cursor="cursor_abc",
        )
        page_two = _graphql_response(
            thread_nodes=[_thread_node(thread_id="T2")],
        )
        runner = QueueRunner(
            [
                ExpectedCall(argv=_graphql_argv(), stdout=json.dumps(page_one)),
                ExpectedCall(
                    argv=_graphql_argv(after="cursor_abc"),
                    stdout=json.dumps(page_two),
                ),
            ]
        )
        result = list_unresolved_review_threads(repo="o/n", pr_number=42, runner=runner)
        assert len(result) == 2
        assert result[0].thread_id == "T1"
        assert result[1].thread_id == "T2"
        runner.assert_exhausted()

    def test_non_dict_payload_raises_value_error(self) -> None:
        runner = QueueRunner([ExpectedCall(argv=_graphql_argv(), stdout=json.dumps([1, 2, 3]))])
        with pytest.raises(ValueError, match="Unexpected GraphQL response"):
            list_unresolved_review_threads(repo="o/n", pr_number=42, runner=runner)


# ---------------------------------------------------------------------------
# Filter helpers
# ---------------------------------------------------------------------------


class TestThreadMatchesPath:
    def test_no_filter_matches_all(self) -> None:
        assert _thread_matches_path(_make_thread(path="any.py"), None) is True

    def test_exact_match(self) -> None:
        assert _thread_matches_path(_make_thread(path="src/app.py"), "src/app.py") is True

    def test_suffix_match(self) -> None:
        assert _thread_matches_path(_make_thread(path="src/app.py"), "app.py") is True

    def test_no_match(self) -> None:
        assert _thread_matches_path(_make_thread(path="src/app.py"), "other.py") is False

    def test_none_path_no_match(self) -> None:
        assert _thread_matches_path(_make_thread(path=None), "app.py") is False


class TestThreadContainsText:
    def test_no_needle_matches_all(self) -> None:
        assert _thread_contains_text(_make_thread(), None) is True

    def test_substring_match_case_insensitive(self) -> None:
        comment = ReviewComment(database_id=1, node_id="C1", author="a", body="Fix This Bug", url="")
        thread = _make_thread(comments=[comment])
        assert _thread_contains_text(thread, "fix this") is True

    def test_no_match(self) -> None:
        comment = ReviewComment(database_id=1, node_id="C1", author="a", body="something else", url="")
        thread = _make_thread(comments=[comment])
        assert _thread_contains_text(thread, "missing") is False


class TestThreadHasAuthor:
    def test_no_filter_matches_all(self) -> None:
        assert _thread_has_author(_make_thread(), None) is True

    def test_exact_author_match(self) -> None:
        assert _thread_has_author(_make_thread(), "alice") is True

    def test_no_author_match(self) -> None:
        assert _thread_has_author(_make_thread(), "bob") is False


class TestThreadMatchesFilters:
    def test_all_none_matches(self) -> None:
        assert (
            _thread_matches_filters(
                _make_thread(),
                path_filter=None,
                line_filter=None,
                needle=None,
                author_filter=None,
            )
            is True
        )

    def test_path_mismatch_fails(self) -> None:
        assert (
            _thread_matches_filters(
                _make_thread(path="a.py"),
                path_filter="b.py",
                line_filter=None,
                needle=None,
                author_filter=None,
            )
            is False
        )

    def test_line_mismatch_fails(self) -> None:
        assert (
            _thread_matches_filters(
                _make_thread(line=10),
                path_filter=None,
                line_filter=99,
                needle=None,
                author_filter=None,
            )
            is False
        )

    def test_text_mismatch_fails(self) -> None:
        assert (
            _thread_matches_filters(
                _make_thread(),
                path_filter=None,
                line_filter=None,
                needle="nonexistent",
                author_filter=None,
            )
            is False
        )

    def test_author_mismatch_fails(self) -> None:
        assert (
            _thread_matches_filters(
                _make_thread(),
                path_filter=None,
                line_filter=None,
                needle=None,
                author_filter="unknown_user",
            )
            is False
        )


class TestFilterReviewThreads:
    def test_no_filters_returns_all(self) -> None:
        threads = [_make_thread(thread_id="T1"), _make_thread(thread_id="T2")]
        assert len(filter_review_threads(threads)) == 2

    def test_path_filter(self) -> None:
        threads = [
            _make_thread(thread_id="T1", path="src/app.py"),
            _make_thread(thread_id="T2", path="src/other.py"),
        ]
        result = filter_review_threads(threads, path="app.py")
        assert len(result) == 1
        assert result[0].thread_id == "T1"

    def test_line_filter(self) -> None:
        threads = [
            _make_thread(thread_id="T1", line=10),
            _make_thread(thread_id="T2", line=20),
        ]
        result = filter_review_threads(threads, line=10)
        assert len(result) == 1
        assert result[0].thread_id == "T1"

    def test_contains_filter(self) -> None:
        comment_match = ReviewComment(database_id=1, node_id="C1", author="a", body="Fix the bug", url="")
        comment_miss = ReviewComment(database_id=2, node_id="C2", author="a", body="Looks good", url="")
        threads = [
            _make_thread(thread_id="T1", comments=[comment_match]),
            _make_thread(thread_id="T2", comments=[comment_miss]),
        ]
        result = filter_review_threads(threads, contains="fix the")
        assert len(result) == 1
        assert result[0].thread_id == "T1"

    def test_author_filter(self) -> None:
        comment_alice = ReviewComment(database_id=1, node_id="C1", author="alice", body="x", url="")
        comment_bob = ReviewComment(database_id=2, node_id="C2", author="bob", body="x", url="")
        threads = [
            _make_thread(thread_id="T1", comments=[comment_alice]),
            _make_thread(thread_id="T2", comments=[comment_bob]),
        ]
        result = filter_review_threads(threads, author="bob")
        assert len(result) == 1
        assert result[0].thread_id == "T2"

    def test_empty_string_filters_treated_as_none(self) -> None:
        threads = [_make_thread()]
        result = filter_review_threads(threads, path="", contains="", author="")
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _build_parser
# ---------------------------------------------------------------------------


class TestBuildParser:
    def test_returns_argument_parser(self) -> None:
        parser = _build_parser()
        assert isinstance(parser, argparse.ArgumentParser)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    def test_success_prints_json(self, monkeypatch, capsys) -> None:
        response = _graphql_response(thread_nodes=[_thread_node(thread_id="T1", is_resolved=False)])
        runner = QueueRunner([ExpectedCall(argv=_graphql_argv(), stdout=json.dumps(response))])
        monkeypatch.setattr("sys.argv", ["prog", "--repo", "o/n", "--pr", "42"])
        monkeypatch.setattr(
            "scripts.github.list_unresolved_review_threads.SubprocessGhRunner",
            lambda: runner,
        )
        exit_code = main()
        assert exit_code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["count"] == 1
        assert len(output["unresolved_threads"]) == 1
        runner.assert_exhausted()

    def test_require_one_exactly_one(self, monkeypatch) -> None:
        response = _graphql_response(thread_nodes=[_thread_node(thread_id="T1", is_resolved=False)])
        runner = QueueRunner([ExpectedCall(argv=_graphql_argv(), stdout=json.dumps(response))])
        monkeypatch.setattr("sys.argv", ["prog", "--repo", "o/n", "--pr", "42", "--require-one"])
        monkeypatch.setattr(
            "scripts.github.list_unresolved_review_threads.SubprocessGhRunner",
            lambda: runner,
        )
        exit_code = main()
        assert exit_code == 0
        runner.assert_exhausted()

    def test_require_one_zero_threads(self, monkeypatch, capsys) -> None:
        response = _graphql_response(thread_nodes=[])
        runner = QueueRunner([ExpectedCall(argv=_graphql_argv(), stdout=json.dumps(response))])
        monkeypatch.setattr("sys.argv", ["prog", "--repo", "o/n", "--pr", "42", "--require-one"])
        monkeypatch.setattr(
            "scripts.github.list_unresolved_review_threads.SubprocessGhRunner",
            lambda: runner,
        )
        exit_code = main()
        assert exit_code == 2
        stderr_output = capsys.readouterr().err
        assert "Expected exactly 1" in stderr_output
        runner.assert_exhausted()

    def test_gh_cli_error_returns_two(self, monkeypatch) -> None:
        monkeypatch.setattr("sys.argv", ["prog", "--repo", "o/n", "--pr", "42"])

        def raising_runner():
            class _FailRunner:
                def run(self, argv, *, input_text=None):
                    raise GhCliError("gh not found", argv=argv, returncode=1, stdout="", stderr="err")

            return _FailRunner()

        monkeypatch.setattr(
            "scripts.github.list_unresolved_review_threads.SubprocessGhRunner",
            raising_runner,
        )
        exit_code = main()
        assert exit_code == 2

    def test_value_error_returns_two(self, monkeypatch) -> None:
        monkeypatch.setattr("sys.argv", ["prog", "--repo", "bad_repo", "--pr", "42"])

        def raising_runner():
            class _FailRunner:
                def run(self, argv, *, input_text=None):
                    raise ValueError("bad repo format")

            return _FailRunner()

        monkeypatch.setattr(
            "scripts.github.list_unresolved_review_threads.SubprocessGhRunner",
            raising_runner,
        )
        exit_code = main()
        assert exit_code == 2
