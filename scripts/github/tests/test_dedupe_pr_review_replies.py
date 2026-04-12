"""Tests for dedupe_pr_review_replies module."""

from __future__ import annotations

import argparse
import json

import pytest

from scripts.github.conftest import ExpectedCall, QueueRunner
from scripts.github.dedupe_pr_review_replies import (
    ReviewReply,
    _build_parser,
    _parse_review_reply,
    _sort_key,
    dedupe_pr_review_replies,
    delete_pr_review_comment,
    find_duplicate_reply_ids,
    list_pr_review_replies,
    main,
)

_REPO = "octo/widgets"
_AUTHOR = "bot-user"


def _valid_payload(
    *,
    comment_id: int = 100,
    in_reply_to: int = 10,
    body: str = "Looks good.",
    created_at: str = "2026-01-15T10:00:00Z",
    login: str = _AUTHOR,
) -> dict:
    return {
        "id": comment_id,
        "in_reply_to": in_reply_to,
        "body": body,
        "created_at": created_at,
        "user": {"login": login},
    }


# -- _build_parser -------------------------------------------------------------


def test_build_parser_returns_argument_parser() -> None:
    parser = _build_parser()
    assert isinstance(parser, argparse.ArgumentParser)


# -- _parse_review_reply -------------------------------------------------------


def test_parse_valid_reply() -> None:
    payload = _valid_payload()
    reply = _parse_review_reply(payload=payload, author=_AUTHOR)
    assert reply is not None
    assert reply.comment_id == 100
    assert reply.in_reply_to == 10
    assert reply.body == "Looks good."
    assert reply.author == _AUTHOR
    assert reply.created_at == "2026-01-15T10:00:00Z"


def test_parse_non_dict_payload_returns_none() -> None:
    assert _parse_review_reply(payload="not-a-dict", author=_AUTHOR) is None


def test_parse_missing_comment_id_returns_none() -> None:
    payload = _valid_payload()
    del payload["id"]
    assert _parse_review_reply(payload=payload, author=_AUTHOR) is None


def test_parse_invalid_comment_id_returns_none() -> None:
    payload = _valid_payload(comment_id=-1)
    assert _parse_review_reply(payload=payload, author=_AUTHOR) is None


def test_parse_invalid_in_reply_to_returns_none() -> None:
    payload = _valid_payload()
    payload["in_reply_to"] = "not-an-int"
    assert _parse_review_reply(payload=payload, author=_AUTHOR) is None


def test_parse_missing_in_reply_to_returns_none() -> None:
    payload = _valid_payload()
    payload["in_reply_to"] = None
    payload.pop("in_reply_to_id", None)
    assert _parse_review_reply(payload=payload, author=_AUTHOR) is None


def test_parse_non_string_body_returns_none() -> None:
    payload = _valid_payload()
    payload["body"] = 42
    assert _parse_review_reply(payload=payload, author=_AUTHOR) is None


def test_parse_non_string_created_at_returns_none() -> None:
    payload = _valid_payload()
    payload["created_at"] = 12345
    assert _parse_review_reply(payload=payload, author=_AUTHOR) is None


def test_parse_wrong_author_returns_none() -> None:
    payload = _valid_payload(login="other-user")
    assert _parse_review_reply(payload=payload, author=_AUTHOR) is None


def test_parse_in_reply_to_id_fallback() -> None:
    payload = _valid_payload()
    payload["in_reply_to"] = None
    payload["in_reply_to_id"] = 55
    reply = _parse_review_reply(payload=payload, author=_AUTHOR)
    assert reply is not None
    assert reply.in_reply_to == 55


def test_parse_user_not_dict_returns_none() -> None:
    payload = _valid_payload()
    payload["user"] = "not-a-dict"
    assert _parse_review_reply(payload=payload, author=_AUTHOR) is None


# -- list_pr_review_replies ----------------------------------------------------


def test_list_pr_review_replies_returns_filtered() -> None:
    api_response = [
        _valid_payload(comment_id=1, in_reply_to=10, login=_AUTHOR),
        _valid_payload(comment_id=2, in_reply_to=10, login="other-user"),
        _valid_payload(comment_id=3, in_reply_to=20, login=_AUTHOR),
    ]
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=["gh", "api", "/repos/octo/widgets/pulls/7/comments", "--paginate"],
                stdout=json.dumps(api_response),
            ),
        ]
    )
    replies = list_pr_review_replies(runner=runner, repo=_REPO, pr_number=7, author=_AUTHOR)
    assert len(replies) == 2
    assert replies[0].comment_id == 1
    assert replies[1].comment_id == 3
    runner.assert_exhausted()


def test_list_pr_review_replies_raises_on_non_list() -> None:
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=["gh", "api", "/repos/octo/widgets/pulls/7/comments", "--paginate"],
                stdout=json.dumps({"error": "unexpected"}),
            ),
        ]
    )
    with pytest.raises(ValueError, match="Unexpected PR review comments payload"):
        list_pr_review_replies(runner=runner, repo=_REPO, pr_number=7, author=_AUTHOR)
    runner.assert_exhausted()


# -- _sort_key -----------------------------------------------------------------


def test_sort_key_normal_datetime() -> None:
    reply = ReviewReply(
        comment_id=1,
        in_reply_to=10,
        body="text",
        author=_AUTHOR,
        created_at="2026-01-15T10:00:00Z",
    )
    key = _sort_key(reply)
    assert key[0] == 10
    assert key[2] == 1


def test_sort_key_invalid_datetime_falls_back() -> None:
    reply = ReviewReply(
        comment_id=2,
        in_reply_to=10,
        body="text",
        author=_AUTHOR,
        created_at="not-a-date",
    )
    from datetime import datetime

    key = _sort_key(reply)
    assert key[1] == datetime.min


# -- find_duplicate_reply_ids --------------------------------------------------


def test_find_duplicate_reply_ids_no_dupes() -> None:
    replies = [
        ReviewReply(comment_id=1, in_reply_to=10, body="A", author=_AUTHOR, created_at="2026-01-15T10:00:00Z"),
        ReviewReply(comment_id=2, in_reply_to=10, body="B", author=_AUTHOR, created_at="2026-01-15T11:00:00Z"),
    ]
    assert find_duplicate_reply_ids(replies) == []


def test_find_duplicate_reply_ids_keeps_earliest() -> None:
    earliest = ReviewReply(
        comment_id=1, in_reply_to=10, body="Same text", author=_AUTHOR, created_at="2026-01-15T08:00:00Z"
    )
    later_dupe = ReviewReply(
        comment_id=2, in_reply_to=10, body="Same text", author=_AUTHOR, created_at="2026-01-15T09:00:00Z"
    )
    latest_dupe = ReviewReply(
        comment_id=3, in_reply_to=10, body="Same text", author=_AUTHOR, created_at="2026-01-15T10:00:00Z"
    )
    delete_ids = find_duplicate_reply_ids([latest_dupe, earliest, later_dupe])
    assert 1 not in delete_ids
    assert sorted(delete_ids) == [2, 3]


# -- delete_pr_review_comment --------------------------------------------------


def test_delete_pr_review_comment() -> None:
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "--method",
                    "DELETE",
                    "/repos/octo/widgets/pulls/comments/999",
                ],
                stdout="",
            ),
        ]
    )
    delete_pr_review_comment(runner=runner, repo=_REPO, comment_id=999)
    runner.assert_exhausted()


# -- dedupe_pr_review_replies --------------------------------------------------


def _make_api_response_with_dupes() -> list[dict]:
    return [
        _valid_payload(comment_id=1, in_reply_to=10, body="Dup body", created_at="2026-01-15T08:00:00Z"),
        _valid_payload(comment_id=2, in_reply_to=10, body="Dup body", created_at="2026-01-15T09:00:00Z"),
        _valid_payload(comment_id=3, in_reply_to=10, body="Unique body", created_at="2026-01-15T10:00:00Z"),
    ]


def test_dedupe_no_duplicates() -> None:
    api_response = [
        _valid_payload(comment_id=1, in_reply_to=10, body="A"),
        _valid_payload(comment_id=2, in_reply_to=10, body="B"),
    ]
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=["gh", "api", "/repos/octo/widgets/pulls/7/comments", "--paginate"],
                stdout=json.dumps(api_response),
            ),
        ]
    )
    result = dedupe_pr_review_replies(runner=runner, repo=_REPO, pr_number=7, author=_AUTHOR, apply=False)
    assert result["duplicate_reply_ids"] == []
    assert result["deleted_count"] == 0
    assert result["total_replies_considered"] == 2
    runner.assert_exhausted()


def test_dedupe_dry_run_does_not_delete() -> None:
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=["gh", "api", "/repos/octo/widgets/pulls/7/comments", "--paginate"],
                stdout=json.dumps(_make_api_response_with_dupes()),
            ),
        ]
    )
    result = dedupe_pr_review_replies(runner=runner, repo=_REPO, pr_number=7, author=_AUTHOR, apply=False)
    assert len(result["duplicate_reply_ids"]) == 1
    assert result["deleted_count"] == 0
    assert result["apply"] is False
    runner.assert_exhausted()


def test_dedupe_apply_deletes() -> None:
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=["gh", "api", "/repos/octo/widgets/pulls/7/comments", "--paginate"],
                stdout=json.dumps(_make_api_response_with_dupes()),
            ),
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "--method",
                    "DELETE",
                    "/repos/octo/widgets/pulls/comments/2",
                ],
                stdout="",
            ),
        ]
    )
    result = dedupe_pr_review_replies(runner=runner, repo=_REPO, pr_number=7, author=_AUTHOR, apply=True)
    assert result["deleted_count"] == 1
    assert result["apply"] is True
    runner.assert_exhausted()


# -- main ----------------------------------------------------------------------


def test_main_json_output(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["dedupe", "--repo", _REPO, "--pr", "7", "--author", _AUTHOR, "--json"],
    )
    api_response = [
        _valid_payload(comment_id=1, in_reply_to=10, body="A"),
    ]
    fake_runner = QueueRunner(
        [
            ExpectedCall(
                argv=["gh", "api", "/repos/octo/widgets/pulls/7/comments", "--paginate"],
                stdout=json.dumps(api_response),
            ),
        ]
    )
    monkeypatch.setattr("scripts.github.dedupe_pr_review_replies.SubprocessGhRunner", lambda: fake_runner)
    exit_code = main()
    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["repo"] == _REPO
    assert output["pr"] == 7
    fake_runner.assert_exhausted()


def test_main_text_dupes_found_dry_run(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["dedupe", "--repo", _REPO, "--pr", "7", "--author", _AUTHOR],
    )
    fake_runner = QueueRunner(
        [
            ExpectedCall(
                argv=["gh", "api", "/repos/octo/widgets/pulls/7/comments", "--paginate"],
                stdout=json.dumps(_make_api_response_with_dupes()),
            ),
        ]
    )
    monkeypatch.setattr("scripts.github.dedupe_pr_review_replies.SubprocessGhRunner", lambda: fake_runner)
    exit_code = main()
    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "duplicate" in captured.lower()
    assert "Dry-run" in captured
    fake_runner.assert_exhausted()


def test_main_text_dupes_found_apply(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["dedupe", "--repo", _REPO, "--pr", "7", "--author", _AUTHOR, "--apply"],
    )
    fake_runner = QueueRunner(
        [
            ExpectedCall(
                argv=["gh", "api", "/repos/octo/widgets/pulls/7/comments", "--paginate"],
                stdout=json.dumps(_make_api_response_with_dupes()),
            ),
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "--method",
                    "DELETE",
                    "/repos/octo/widgets/pulls/comments/2",
                ],
                stdout="",
            ),
        ]
    )
    monkeypatch.setattr("scripts.github.dedupe_pr_review_replies.SubprocessGhRunner", lambda: fake_runner)
    exit_code = main()
    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "Deleted duplicates" in captured
    fake_runner.assert_exhausted()


def test_main_text_no_duplicates(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["dedupe", "--repo", _REPO, "--pr", "7", "--author", _AUTHOR],
    )
    api_response = [_valid_payload(comment_id=1, in_reply_to=10, body="Unique")]
    fake_runner = QueueRunner(
        [
            ExpectedCall(
                argv=["gh", "api", "/repos/octo/widgets/pulls/7/comments", "--paginate"],
                stdout=json.dumps(api_response),
            ),
        ]
    )
    monkeypatch.setattr("scripts.github.dedupe_pr_review_replies.SubprocessGhRunner", lambda: fake_runner)
    exit_code = main()
    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "No duplicate" in captured
    fake_runner.assert_exhausted()


def test_main_handles_gh_cli_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.github.gh_cli import GhCliError

    monkeypatch.setattr(
        "sys.argv",
        ["dedupe", "--repo", _REPO, "--pr", "7", "--author", _AUTHOR],
    )

    def raise_error() -> QueueRunner:
        msg = "gh failed"
        raise GhCliError(msg, argv=["gh"], returncode=1, stdout="", stderr="oops")

    monkeypatch.setattr("scripts.github.dedupe_pr_review_replies.SubprocessGhRunner", raise_error)
    exit_code = main()
    assert exit_code == 2


def test_main_handles_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["dedupe", "--repo", _REPO, "--pr", "7", "--author", _AUTHOR],
    )

    def raise_error() -> QueueRunner:
        msg = "bad value"
        raise ValueError(msg)

    monkeypatch.setattr("scripts.github.dedupe_pr_review_replies.SubprocessGhRunner", raise_error)
    exit_code = main()
    assert exit_code == 2
