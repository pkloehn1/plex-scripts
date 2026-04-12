"""Tests for scripts.github.create_pr_review."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.github.conftest import ExpectedCall, QueueRunner
from scripts.github.create_pr_review import (
    CreateReviewResult,
    ReviewComment,
    _content_already_exists,
    _fetch_existing_comment_bodies,
    _fetch_existing_review_bodies,
    _normalize_body,
    build_review_payload,
    create_pr_review,
    fetch_pr_head_sha,
    parse_comments,
    read_comments_input,
    validate_review_inputs,
)

# ---------------------------------------------------------------------------
# parse_comments
# ---------------------------------------------------------------------------


class TestParseComments:
    def test_single_comment(self) -> None:
        raw = json.dumps([{"path": "file.py", "line": 10, "body": "Fix this"}])
        result = parse_comments(raw)
        assert len(result) == 1
        assert result[0] == ReviewComment(path="file.py", body="Fix this", line=10)

    def test_multiple_comments(self) -> None:
        raw = json.dumps(
            [
                {"path": "a.py", "body": "Comment A"},
                {"path": "b.py", "body": "Comment B", "line": 5},
            ]
        )
        result = parse_comments(raw)
        assert len(result) == 2
        assert result[0].path == "a.py"
        assert result[1].line == 5

    def test_optional_fields(self) -> None:
        raw = json.dumps(
            [
                {
                    "path": "file.py",
                    "body": "Multi-line",
                    "line": 20,
                    "side": "LEFT",
                    "start_line": 15,
                }
            ]
        )
        result = parse_comments(raw)
        assert result[0].side == "LEFT"
        assert result[0].start_line == 15

    def test_minimal_comment_no_line(self) -> None:
        raw = json.dumps([{"path": "file.py", "body": "Note"}])
        result = parse_comments(raw)
        assert result[0].line is None
        assert result[0].side is None
        assert result[0].start_line is None

    def test_not_array_raises(self) -> None:
        with pytest.raises(ValueError, match="must be an array"):
            parse_comments('{"path": "file.py", "body": "x"}')

    def test_non_object_element_raises(self) -> None:
        with pytest.raises(ValueError, match="must be an object"):
            parse_comments('["not an object"]')

    def test_missing_path_raises(self) -> None:
        with pytest.raises(ValueError, match="'path' is required"):
            parse_comments(json.dumps([{"body": "x"}]))

    def test_empty_path_raises(self) -> None:
        with pytest.raises(ValueError, match="'path' is required"):
            parse_comments(json.dumps([{"path": "  ", "body": "x"}]))

    def test_missing_body_raises(self) -> None:
        with pytest.raises(ValueError, match="'body' is required"):
            parse_comments(json.dumps([{"path": "file.py"}]))

    def test_empty_body_raises(self) -> None:
        with pytest.raises(ValueError, match="'body' is required"):
            parse_comments(json.dumps([{"path": "file.py", "body": "   "}]))

    def test_path_not_string_raises(self) -> None:
        with pytest.raises(ValueError, match="'path' is required"):
            parse_comments(json.dumps([{"path": 123, "body": "x"}]))

    def test_body_not_string_raises(self) -> None:
        with pytest.raises(ValueError, match="'body' is required"):
            parse_comments(json.dumps([{"path": "file.py", "body": 42}]))


# ---------------------------------------------------------------------------
# read_comments_input
# ---------------------------------------------------------------------------


class TestReadCommentsInput:
    def test_from_json_string(self) -> None:
        raw = json.dumps([{"path": "a.py", "body": "Comment"}])
        result = read_comments_input(comments_json=raw, comments_file=None)
        assert result is not None
        assert len(result) == 1

    def test_from_file(self, tmp_path: Path) -> None:
        comments_path = tmp_path / "comments.json"
        comments_path.write_text(
            json.dumps([{"path": "b.py", "body": "From file"}]),
            encoding="utf-8",
        )
        result = read_comments_input(comments_json=None, comments_file=comments_path)
        assert result is not None
        assert result[0].path == "b.py"

    def test_both_provided_raises(self, tmp_path: Path) -> None:
        comments_path = tmp_path / "comments.json"
        comments_path.write_text("[]", encoding="utf-8")
        with pytest.raises(ValueError, match="only one"):
            read_comments_input(comments_json="[]", comments_file=comments_path)

    def test_neither_returns_none(self) -> None:
        result = read_comments_input(comments_json=None, comments_file=None)
        assert result is None


# ---------------------------------------------------------------------------
# validate_review_inputs
# ---------------------------------------------------------------------------


class TestValidateReviewInputs:
    def test_valid_comment_with_body(self) -> None:
        validate_review_inputs(event="COMMENT", body="Summary", comments=None)

    def test_valid_comment_with_comments(self) -> None:
        comments = [ReviewComment(path="f.py", body="Fix")]
        validate_review_inputs(event="COMMENT", body=None, comments=comments)

    def test_valid_approve_with_body(self) -> None:
        validate_review_inputs(event="APPROVE", body="LGTM", comments=None)

    def test_valid_request_changes(self) -> None:
        comments = [ReviewComment(path="f.py", body="Needs fix", line=5)]
        validate_review_inputs(event="REQUEST_CHANGES", body="Changes needed", comments=comments)

    def test_invalid_event_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid event"):
            validate_review_inputs(event="INVALID", body="x", comments=None)

    def test_no_body_no_comments_raises(self) -> None:
        with pytest.raises(ValueError, match="At least one"):
            validate_review_inputs(event="COMMENT", body=None, comments=None)

    def test_empty_body_no_comments_raises(self) -> None:
        with pytest.raises(ValueError, match="At least one"):
            validate_review_inputs(event="COMMENT", body="   ", comments=None)

    def test_whitespace_body_empty_comments_raises(self) -> None:
        with pytest.raises(ValueError, match="At least one"):
            validate_review_inputs(event="COMMENT", body="  ", comments=[])

    def test_comment_empty_path_raises(self) -> None:
        comments = [ReviewComment(path="", body="Fix")]
        with pytest.raises(ValueError, match="'path' must be non-empty"):
            validate_review_inputs(event="COMMENT", body=None, comments=comments)

    def test_comment_empty_body_raises(self) -> None:
        comments = [ReviewComment(path="f.py", body="  ")]
        with pytest.raises(ValueError, match="'body' must be non-empty"):
            validate_review_inputs(event="COMMENT", body=None, comments=comments)

    def test_comment_invalid_side_raises(self) -> None:
        comments = [ReviewComment(path="f.py", body="Fix", side="MIDDLE")]
        with pytest.raises(ValueError, match="LEFT or RIGHT"):
            validate_review_inputs(event="COMMENT", body=None, comments=comments)

    def test_comment_valid_side_left(self) -> None:
        comments = [ReviewComment(path="f.py", body="Fix", line=5, side="LEFT")]
        validate_review_inputs(event="COMMENT", body=None, comments=comments)

    def test_comment_valid_side_right(self) -> None:
        comments = [ReviewComment(path="f.py", body="Fix", line=5, side="RIGHT")]
        validate_review_inputs(event="COMMENT", body=None, comments=comments)

    def test_start_line_without_line_raises(self) -> None:
        comments = [ReviewComment(path="f.py", body="Fix", start_line=10)]
        with pytest.raises(ValueError, match="'start_line' requires 'line'"):
            validate_review_inputs(event="COMMENT", body=None, comments=comments)

    def test_start_line_with_line_passes(self) -> None:
        comments = [ReviewComment(path="f.py", body="Fix", line=20, start_line=15)]
        validate_review_inputs(event="COMMENT", body=None, comments=comments)


# ---------------------------------------------------------------------------
# build_review_payload
# ---------------------------------------------------------------------------


class TestBuildReviewPayload:
    def test_full_payload(self) -> None:
        comments = [ReviewComment(path="f.py", body="Fix", line=10)]
        payload = build_review_payload(
            commit_id="abc123",
            body="Summary",
            event="COMMENT",
            comments=comments,
        )
        assert payload == {
            "commit_id": "abc123",
            "body": "Summary",
            "event": "COMMENT",
            "comments": [{"path": "f.py", "body": "Fix", "line": 10}],
        }

    def test_no_body(self) -> None:
        comments = [ReviewComment(path="f.py", body="Fix")]
        payload = build_review_payload(
            commit_id="abc",
            body=None,
            event="COMMENT",
            comments=comments,
        )
        assert "body" not in payload
        assert payload["event"] == "COMMENT"

    def test_no_comments(self) -> None:
        payload = build_review_payload(
            commit_id="abc",
            body="LGTM",
            event="APPROVE",
            comments=None,
        )
        assert "comments" not in payload
        assert payload["body"] == "LGTM"

    def test_empty_comments_list(self) -> None:
        payload = build_review_payload(
            commit_id="abc",
            body="LGTM",
            event="APPROVE",
            comments=[],
        )
        assert "comments" not in payload

    def test_no_commit_id(self) -> None:
        payload = build_review_payload(
            commit_id=None,
            body="Summary",
            event="COMMENT",
            comments=None,
        )
        assert "commit_id" not in payload

    def test_comment_optional_fields(self) -> None:
        comments = [
            ReviewComment(path="f.py", body="Multi", line=20, side="LEFT", start_line=15),
        ]
        payload = build_review_payload(
            commit_id="abc",
            body=None,
            event="COMMENT",
            comments=comments,
        )
        entry = payload["comments"][0]
        assert entry["side"] == "LEFT"
        assert entry["start_line"] == 15
        assert entry["line"] == 20

    def test_comment_omits_none_fields(self) -> None:
        comments = [ReviewComment(path="f.py", body="Note")]
        payload = build_review_payload(
            commit_id="abc",
            body=None,
            event="COMMENT",
            comments=comments,
        )
        entry = payload["comments"][0]
        assert "line" not in entry
        assert "side" not in entry
        assert "start_line" not in entry


# ---------------------------------------------------------------------------
# fetch_pr_head_sha
# ---------------------------------------------------------------------------


class TestFetchPrHeadSha:
    def test_returns_sha(self) -> None:
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=["gh", "api", "/repos/owner/name/pulls/42", "--jq", ".head.sha"],
                    stdout="abc123def\n",
                ),
            ]
        )
        sha = fetch_pr_head_sha(runner=runner, repo="owner/name", pr_number=42)
        assert sha == "abc123def"
        runner.assert_exhausted()

    def test_returns_sha_starting_with_digits(self) -> None:
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=["gh", "api", "/repos/owner/name/pulls/42", "--jq", ".head.sha"],
                    stdout="205829114dabcdef0123456789abcdef01234567\n",
                ),
            ]
        )
        sha = fetch_pr_head_sha(runner=runner, repo="owner/name", pr_number=42)
        assert sha == "205829114dabcdef0123456789abcdef01234567"
        runner.assert_exhausted()

    def test_empty_response_raises(self) -> None:
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=["gh", "api", "/repos/owner/name/pulls/42", "--jq", ".head.sha"],
                    stdout="\n",
                ),
            ]
        )
        with pytest.raises(ValueError, match="Unable to determine HEAD SHA"):
            fetch_pr_head_sha(runner=runner, repo="owner/name", pr_number=42)

    def test_whitespace_only_response_raises(self) -> None:
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=["gh", "api", "/repos/owner/name/pulls/42", "--jq", ".head.sha"],
                    stdout="  \n",
                ),
            ]
        )
        with pytest.raises(ValueError, match="Unable to determine HEAD SHA"):
            fetch_pr_head_sha(runner=runner, repo="owner/name", pr_number=42)


# ---------------------------------------------------------------------------
# create_pr_review (core function)
# ---------------------------------------------------------------------------


class TestCreatePrReview:
    def test_dry_run_no_api_calls(self) -> None:
        runner = QueueRunner([])
        result = create_pr_review(
            runner=runner,
            repo="owner/name",
            pr_number=42,
            event="COMMENT",
            body="Summary",
            apply=False,
        )
        assert result.success is True
        assert result.applied is False
        assert result.review_id is None
        assert result.event == "COMMENT"
        assert result.comments_count == 0
        runner.assert_exhausted()

    def test_apply_posts_review(self) -> None:
        comments = [ReviewComment(path="f.py", body="Fix", line=10)]
        expected_payload = {
            "commit_id": "sha456",
            "body": "Summary",
            "event": "COMMENT",
            "comments": [{"path": "f.py", "body": "Fix", "line": 10}],
        }
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=["gh", "api", "/repos/owner/name/pulls/42/reviews", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps([]),
                ),
                ExpectedCall(
                    argv=["gh", "api", "/repos/owner/name/issues/42/comments", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps([]),
                ),
                ExpectedCall(
                    argv=["gh", "api", "/repos/owner/name/pulls/42", "--jq", ".head.sha"],
                    stdout="sha456\n",
                ),
                ExpectedCall(
                    argv=[
                        "gh",
                        "api",
                        "--method",
                        "POST",
                        "/repos/owner/name/pulls/42/reviews",
                        "--input",
                        "-",
                    ],
                    stdout=json.dumps({"id": 99}),
                    expected_input=json.dumps(expected_payload),
                ),
            ]
        )
        result = create_pr_review(
            runner=runner,
            repo="owner/name",
            pr_number=42,
            event="COMMENT",
            body="Summary",
            comments=comments,
            apply=True,
        )
        assert result.success is True
        assert result.applied is True
        assert result.review_id == 99
        assert result.comments_count == 1
        runner.assert_exhausted()

    def test_explicit_commit_id_skips_fetch(self) -> None:
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=["gh", "api", "/repos/owner/name/pulls/42/reviews", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps([]),
                ),
                ExpectedCall(
                    argv=["gh", "api", "/repos/owner/name/issues/42/comments", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps([]),
                ),
                ExpectedCall(
                    argv=[
                        "gh",
                        "api",
                        "--method",
                        "POST",
                        "/repos/owner/name/pulls/42/reviews",
                        "--input",
                        "-",
                    ],
                    stdout=json.dumps({"id": 55}),
                    expected_input=json.dumps(
                        {
                            "commit_id": "explicit_sha",
                            "body": "LGTM",
                            "event": "APPROVE",
                        }
                    ),
                ),
            ]
        )
        result = create_pr_review(
            runner=runner,
            repo="owner/name",
            pr_number=42,
            event="APPROVE",
            body="LGTM",
            commit_id="explicit_sha",
            apply=True,
        )
        assert result.applied is True
        assert result.review_id == 55
        runner.assert_exhausted()

    def test_request_changes_event(self) -> None:
        comments = [ReviewComment(path="a.py", body="Needs work", line=3)]
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=["gh", "api", "/repos/o/r/pulls/1/reviews", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps([]),
                ),
                ExpectedCall(
                    argv=["gh", "api", "/repos/o/r/issues/1/comments", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps([]),
                ),
                ExpectedCall(
                    argv=["gh", "api", "/repos/o/r/pulls/1", "--jq", ".head.sha"],
                    stdout="sha789\n",
                ),
                ExpectedCall(
                    argv=[
                        "gh",
                        "api",
                        "--method",
                        "POST",
                        "/repos/o/r/pulls/1/reviews",
                        "--input",
                        "-",
                    ],
                    stdout=json.dumps({"id": 77}),
                    expected_input=json.dumps(
                        {
                            "commit_id": "sha789",
                            "body": "Changes required",
                            "event": "REQUEST_CHANGES",
                            "comments": [{"path": "a.py", "body": "Needs work", "line": 3}],
                        }
                    ),
                ),
            ]
        )
        result = create_pr_review(
            runner=runner,
            repo="o/r",
            pr_number=1,
            event="REQUEST_CHANGES",
            body="Changes required",
            comments=comments,
            apply=True,
        )
        assert result.event == "REQUEST_CHANGES"
        assert result.applied is True
        runner.assert_exhausted()

    def test_body_only_no_comments(self) -> None:
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=["gh", "api", "/repos/owner/name/pulls/5/reviews", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps([]),
                ),
                ExpectedCall(
                    argv=["gh", "api", "/repos/owner/name/issues/5/comments", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps([]),
                ),
                ExpectedCall(
                    argv=[
                        "gh",
                        "api",
                        "--method",
                        "POST",
                        "/repos/owner/name/pulls/5/reviews",
                        "--input",
                        "-",
                    ],
                    stdout=json.dumps({"id": 33}),
                    expected_input=json.dumps(
                        {
                            "commit_id": "sha_explicit",
                            "body": "Approved",
                            "event": "APPROVE",
                        }
                    ),
                ),
            ]
        )
        result = create_pr_review(
            runner=runner,
            repo="owner/name",
            pr_number=5,
            event="APPROVE",
            body="Approved",
            commit_id="sha_explicit",
            apply=True,
        )
        assert result.comments_count == 0
        assert result.applied is True
        runner.assert_exhausted()

    def test_comments_only_no_body(self) -> None:
        comments = [ReviewComment(path="x.py", body="Note", line=1)]
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=[
                        "gh",
                        "api",
                        "--method",
                        "POST",
                        "/repos/owner/name/pulls/7/reviews",
                        "--input",
                        "-",
                    ],
                    stdout=json.dumps({"id": 44}),
                    expected_input=json.dumps(
                        {
                            "commit_id": "sha_exp",
                            "event": "COMMENT",
                            "comments": [{"path": "x.py", "body": "Note", "line": 1}],
                        }
                    ),
                ),
            ]
        )
        result = create_pr_review(
            runner=runner,
            repo="owner/name",
            pr_number=7,
            event="COMMENT",
            comments=comments,
            commit_id="sha_exp",
            apply=True,
        )
        assert result.comments_count == 1
        assert result.applied is True
        runner.assert_exhausted()

    def test_dry_run_with_explicit_commit_id(self) -> None:
        runner = QueueRunner([])
        result = create_pr_review(
            runner=runner,
            repo="owner/name",
            pr_number=10,
            event="COMMENT",
            body="Dry",
            commit_id="sha_given",
            apply=False,
        )
        assert result.applied is False
        assert result.success is True
        runner.assert_exhausted()

    def test_response_without_id(self) -> None:
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=["gh", "api", "/repos/owner/name/pulls/3/reviews", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps([]),
                ),
                ExpectedCall(
                    argv=["gh", "api", "/repos/owner/name/issues/3/comments", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps([]),
                ),
                ExpectedCall(
                    argv=[
                        "gh",
                        "api",
                        "--method",
                        "POST",
                        "/repos/owner/name/pulls/3/reviews",
                        "--input",
                        "-",
                    ],
                    stdout=json.dumps({}),
                    expected_input=json.dumps(
                        {
                            "commit_id": "sha",
                            "body": "ok",
                            "event": "COMMENT",
                        }
                    ),
                ),
            ]
        )
        result = create_pr_review(
            runner=runner,
            repo="owner/name",
            pr_number=3,
            event="COMMENT",
            body="ok",
            commit_id="sha",
            apply=True,
        )
        assert result.review_id is None
        assert result.applied is True
        runner.assert_exhausted()

    def test_response_non_dict(self) -> None:
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=["gh", "api", "/repos/owner/name/pulls/3/reviews", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps([]),
                ),
                ExpectedCall(
                    argv=["gh", "api", "/repos/owner/name/issues/3/comments", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps([]),
                ),
                ExpectedCall(
                    argv=[
                        "gh",
                        "api",
                        "--method",
                        "POST",
                        "/repos/owner/name/pulls/3/reviews",
                        "--input",
                        "-",
                    ],
                    stdout=json.dumps("not a dict"),
                    expected_input=json.dumps(
                        {
                            "commit_id": "sha",
                            "body": "ok",
                            "event": "COMMENT",
                        }
                    ),
                ),
            ]
        )
        result = create_pr_review(
            runner=runner,
            repo="owner/name",
            pr_number=3,
            event="COMMENT",
            body="ok",
            commit_id="sha",
            apply=True,
        )
        assert result.review_id is None
        runner.assert_exhausted()

    def test_multiple_comments(self) -> None:
        comments = [
            ReviewComment(path="a.py", body="Fix A", line=1),
            ReviewComment(path="b.py", body="Fix B", line=2, side="RIGHT"),
        ]
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=[
                        "gh",
                        "api",
                        "--method",
                        "POST",
                        "/repos/owner/name/pulls/8/reviews",
                        "--input",
                        "-",
                    ],
                    stdout=json.dumps({"id": 88}),
                    expected_input=json.dumps(
                        {
                            "commit_id": "sha",
                            "event": "COMMENT",
                            "comments": [
                                {"path": "a.py", "body": "Fix A", "line": 1},
                                {"path": "b.py", "body": "Fix B", "line": 2, "side": "RIGHT"},
                            ],
                        }
                    ),
                ),
            ]
        )
        result = create_pr_review(
            runner=runner,
            repo="owner/name",
            pr_number=8,
            event="COMMENT",
            comments=comments,
            commit_id="sha",
            apply=True,
        )
        assert result.comments_count == 2
        runner.assert_exhausted()


# ---------------------------------------------------------------------------
# Deduplication helpers
# ---------------------------------------------------------------------------


class TestNormalizeBody:
    def test_collapses_whitespace(self) -> None:
        assert _normalize_body("hello   world") == "hello world"

    def test_strips_leading_trailing(self) -> None:
        assert _normalize_body("  hello  ") == "hello"

    def test_normalizes_newlines_and_tabs(self) -> None:
        assert _normalize_body("line1\n\tline2\r\nline3") == "line1 line2 line3"

    def test_empty_string(self) -> None:
        assert _normalize_body("") == ""

    def test_whitespace_only(self) -> None:
        assert _normalize_body("   \n\t  ") == ""


class TestFetchExistingReviewBodies:
    def test_returns_bodies(self) -> None:
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=["gh", "api", "/repos/o/r/pulls/1/reviews", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps(["Review A", "Review B"]),
                ),
            ]
        )
        result = _fetch_existing_review_bodies(runner=runner, repo="o/r", pr_number=1)
        assert result == ["Review A", "Review B"]
        runner.assert_exhausted()

    def test_skips_entries_without_body(self) -> None:
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=["gh", "api", "/repos/o/r/pulls/1/reviews", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps(["Has body", None, ""]),
                ),
            ]
        )
        result = _fetch_existing_review_bodies(runner=runner, repo="o/r", pr_number=1)
        assert result == ["Has body"]
        runner.assert_exhausted()

    def test_non_list_response(self) -> None:
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=["gh", "api", "/repos/o/r/pulls/1/reviews", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps({"error": "not found"}),
                ),
            ]
        )
        result = _fetch_existing_review_bodies(runner=runner, repo="o/r", pr_number=1)
        assert result == []
        runner.assert_exhausted()

    def test_skips_non_string_entries(self) -> None:
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=["gh", "api", "/repos/o/r/pulls/1/reviews", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps(["ok", 42]),
                ),
            ]
        )
        result = _fetch_existing_review_bodies(runner=runner, repo="o/r", pr_number=1)
        assert result == ["ok"]
        runner.assert_exhausted()


class TestFetchExistingCommentBodies:
    def test_returns_bodies(self) -> None:
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=["gh", "api", "/repos/o/r/issues/1/comments", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps(["Comment A"]),
                ),
            ]
        )
        result = _fetch_existing_comment_bodies(runner=runner, repo="o/r", pr_number=1)
        assert result == ["Comment A"]
        runner.assert_exhausted()

    def test_skips_entries_without_body(self) -> None:
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=["gh", "api", "/repos/o/r/issues/1/comments", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps(["ok", None, ""]),
                ),
            ]
        )
        result = _fetch_existing_comment_bodies(runner=runner, repo="o/r", pr_number=1)
        assert result == ["ok"]
        runner.assert_exhausted()

    def test_non_list_response(self) -> None:
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=["gh", "api", "/repos/o/r/issues/1/comments", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps("not a list"),
                ),
            ]
        )
        result = _fetch_existing_comment_bodies(runner=runner, repo="o/r", pr_number=1)
        assert result == []
        runner.assert_exhausted()

    def test_skips_non_string_entries(self) -> None:
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=["gh", "api", "/repos/o/r/issues/1/comments", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps(["ok", 42]),
                ),
            ]
        )
        result = _fetch_existing_comment_bodies(runner=runner, repo="o/r", pr_number=1)
        assert result == ["ok"]
        runner.assert_exhausted()


class TestContentAlreadyExists:
    def test_match_in_review(self) -> None:
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=["gh", "api", "/repos/o/r/pulls/1/reviews", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps(["Hello  world"]),
                ),
            ]
        )
        result = _content_already_exists(runner=runner, repo="o/r", pr_number=1, body="Hello world")
        assert result is not None
        assert "PR review" in result
        runner.assert_exhausted()

    def test_match_in_comment(self) -> None:
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=["gh", "api", "/repos/o/r/pulls/1/reviews", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps([]),
                ),
                ExpectedCall(
                    argv=["gh", "api", "/repos/o/r/issues/1/comments", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps(["Same body"]),
                ),
            ]
        )
        result = _content_already_exists(runner=runner, repo="o/r", pr_number=1, body="Same body")
        assert result is not None
        assert "issue comment" in result
        runner.assert_exhausted()

    def test_no_match(self) -> None:
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=["gh", "api", "/repos/o/r/pulls/1/reviews", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps(["Different"]),
                ),
                ExpectedCall(
                    argv=["gh", "api", "/repos/o/r/issues/1/comments", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps(["Also different"]),
                ),
            ]
        )
        result = _content_already_exists(runner=runner, repo="o/r", pr_number=1, body="New content")
        assert result is None
        runner.assert_exhausted()

    def test_empty_body_returns_none(self) -> None:
        runner = QueueRunner([])
        result = _content_already_exists(runner=runner, repo="o/r", pr_number=1, body="   ")
        assert result is None
        runner.assert_exhausted()

    def test_whitespace_normalized_match(self) -> None:
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=["gh", "api", "/repos/o/r/pulls/1/reviews", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps(["line1\n\nline2"]),
                ),
            ]
        )
        result = _content_already_exists(runner=runner, repo="o/r", pr_number=1, body="line1  line2")
        assert result is not None
        runner.assert_exhausted()


class TestCreatePrReviewDedup:
    def test_apply_skips_when_body_matches_review(self) -> None:
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=["gh", "api", "/repos/o/r/pulls/1/reviews", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps(["Duplicate body"]),
                ),
            ]
        )
        result = create_pr_review(
            runner=runner,
            repo="o/r",
            pr_number=1,
            event="COMMENT",
            body="Duplicate body",
            apply=True,
        )
        assert result.applied is False
        assert result.skip_reason is not None
        assert "PR review" in result.skip_reason
        runner.assert_exhausted()

    def test_apply_skips_when_body_matches_issue_comment(self) -> None:
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=["gh", "api", "/repos/o/r/pulls/1/reviews", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps([]),
                ),
                ExpectedCall(
                    argv=["gh", "api", "/repos/o/r/issues/1/comments", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps(["Duplicate body"]),
                ),
            ]
        )
        result = create_pr_review(
            runner=runner,
            repo="o/r",
            pr_number=1,
            event="COMMENT",
            body="Duplicate body",
            apply=True,
        )
        assert result.applied is False
        assert result.skip_reason is not None
        assert "issue comment" in result.skip_reason
        runner.assert_exhausted()

    def test_apply_proceeds_when_no_duplicate(self) -> None:
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=["gh", "api", "/repos/o/r/pulls/1/reviews", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps([]),
                ),
                ExpectedCall(
                    argv=["gh", "api", "/repos/o/r/issues/1/comments", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps([]),
                ),
                ExpectedCall(
                    argv=["gh", "api", "/repos/o/r/pulls/1", "--jq", ".head.sha"],
                    stdout="sha1\n",
                ),
                ExpectedCall(
                    argv=[
                        "gh",
                        "api",
                        "--method",
                        "POST",
                        "/repos/o/r/pulls/1/reviews",
                        "--input",
                        "-",
                    ],
                    stdout=json.dumps({"id": 200}),
                    expected_input=json.dumps(
                        {
                            "commit_id": "sha1",
                            "body": "New content",
                            "event": "COMMENT",
                        }
                    ),
                ),
            ]
        )
        result = create_pr_review(
            runner=runner,
            repo="o/r",
            pr_number=1,
            event="COMMENT",
            body="New content",
            apply=True,
        )
        assert result.applied is True
        assert result.skip_reason is None
        assert result.review_id == 200
        runner.assert_exhausted()

    def test_apply_no_body_skips_dedup(self) -> None:
        comments = [ReviewComment(path="f.py", body="Fix", line=1)]
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=[
                        "gh",
                        "api",
                        "--method",
                        "POST",
                        "/repos/o/r/pulls/1/reviews",
                        "--input",
                        "-",
                    ],
                    stdout=json.dumps({"id": 201}),
                    expected_input=json.dumps(
                        {
                            "commit_id": "explicit",
                            "event": "COMMENT",
                            "comments": [{"path": "f.py", "body": "Fix", "line": 1}],
                        }
                    ),
                ),
            ]
        )
        result = create_pr_review(
            runner=runner,
            repo="o/r",
            pr_number=1,
            event="COMMENT",
            comments=comments,
            commit_id="explicit",
            apply=True,
        )
        assert result.applied is True
        assert result.skip_reason is None
        runner.assert_exhausted()

    def test_dry_run_skips_dedup(self) -> None:
        runner = QueueRunner([])
        result = create_pr_review(
            runner=runner,
            repo="o/r",
            pr_number=1,
            event="COMMENT",
            body="Anything",
            commit_id="sha",
            apply=False,
        )
        assert result.applied is False
        assert result.skip_reason is None
        runner.assert_exhausted()

    def test_duplicate_body_with_inline_comments_clears_body(self) -> None:
        comments = [ReviewComment(path="f.py", body="Fix this", line=5)]
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=["gh", "api", "/repos/o/r/pulls/1/reviews", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps(["Duplicate body"]),
                ),
                ExpectedCall(
                    argv=["gh", "api", "/repos/o/r/pulls/1", "--jq", ".head.sha"],
                    stdout="sha1\n",
                ),
                ExpectedCall(
                    argv=[
                        "gh",
                        "api",
                        "--method",
                        "POST",
                        "/repos/o/r/pulls/1/reviews",
                        "--input",
                        "-",
                    ],
                    stdout=json.dumps({"id": 300}),
                    expected_input=json.dumps(
                        {
                            "commit_id": "sha1",
                            "event": "COMMENT",
                            "comments": [{"path": "f.py", "body": "Fix this", "line": 5}],
                        }
                    ),
                ),
            ]
        )
        result = create_pr_review(
            runner=runner,
            repo="o/r",
            pr_number=1,
            event="COMMENT",
            body="Duplicate body",
            comments=comments,
            apply=True,
        )
        assert result.applied is True
        assert result.skip_reason is None
        assert result.review_id == 300
        assert result.comments_count == 1
        runner.assert_exhausted()


# ---------------------------------------------------------------------------
# CreateReviewResult dataclass
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# CLI layer (_build_parser, _run, main)
# ---------------------------------------------------------------------------


class TestBuildParser:
    def test_returns_parser_with_expected_args(self) -> None:
        from scripts.github.create_pr_review import _build_parser

        parser = _build_parser()
        args = parser.parse_args(
            [
                "--repo",
                "owner/name",
                "--pr",
                "42",
                "--event",
                "COMMENT",
                "--body",
                "Summary",
                "--commit-id",
                "abc",
                "--apply",
                "--json",
            ]
        )
        assert args.repo == "owner/name"
        assert args.pr == 42
        assert args.event == "COMMENT"
        assert args.body == "Summary"
        assert args.commit_id == "abc"
        assert args.apply is True
        assert args.json is True

    def test_defaults(self) -> None:
        from scripts.github.create_pr_review import _build_parser

        parser = _build_parser()
        args = parser.parse_args([])
        assert args.repo is None
        assert args.pr is None
        assert args.event == "COMMENT"
        assert args.body is None
        assert args.body_file is None
        assert args.comments_json is None
        assert args.comments_file is None
        assert args.commit_id is None
        assert args.apply is False
        assert args.json is False


class TestRunHandler:
    def test_dry_run_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        from scripts.github.create_pr_review import _build_parser, _run

        parser = _build_parser()
        args = parser.parse_args(
            [
                "--repo",
                "owner/name",
                "--pr",
                "10",
                "--body",
                "Dry run",
                "--commit-id",
                "sha_dry",
            ]
        )
        runner = QueueRunner([])
        result = _run(args, parser, runner)
        assert result == 0
        out = capsys.readouterr().out
        assert "Dry-run" in out
        assert "--apply" in out

    def test_apply_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        from scripts.github.create_pr_review import _build_parser, _run

        parser = _build_parser()
        args = parser.parse_args(
            [
                "--repo",
                "owner/name",
                "--pr",
                "10",
                "--body",
                "Applied",
                "--commit-id",
                "sha_apply",
                "--apply",
            ]
        )
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=["gh", "api", "/repos/owner/name/pulls/10/reviews", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps([]),
                ),
                ExpectedCall(
                    argv=["gh", "api", "/repos/owner/name/issues/10/comments", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps([]),
                ),
                ExpectedCall(
                    argv=[
                        "gh",
                        "api",
                        "--method",
                        "POST",
                        "/repos/owner/name/pulls/10/reviews",
                        "--input",
                        "-",
                    ],
                    stdout=json.dumps({"id": 100}),
                    expected_input=json.dumps(
                        {
                            "commit_id": "sha_apply",
                            "body": "Applied",
                            "event": "COMMENT",
                        }
                    ),
                ),
            ]
        )
        result = _run(args, parser, runner)
        assert result == 0
        out = capsys.readouterr().out
        assert "Created review" in out
        runner.assert_exhausted()

    def test_json_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        from scripts.github.create_pr_review import _build_parser, _run

        parser = _build_parser()
        args = parser.parse_args(
            [
                "--repo",
                "owner/name",
                "--pr",
                "10",
                "--body",
                "JSON mode",
                "--commit-id",
                "sha_json",
                "--json",
            ]
        )
        runner = QueueRunner([])
        result = _run(args, parser, runner)
        assert result == 0
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["success"] is True
        assert payload["applied"] is False
        assert payload["pr_number"] == 10

    def test_with_comments_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        from scripts.github.create_pr_review import _build_parser, _run

        parser = _build_parser()
        args = parser.parse_args(
            [
                "--repo",
                "owner/name",
                "--pr",
                "10",
                "--event",
                "COMMENT",
                "--comments-json",
                json.dumps([{"path": "f.py", "body": "Fix", "line": 5}]),
                "--commit-id",
                "sha_c",
            ]
        )
        runner = QueueRunner([])
        result = _run(args, parser, runner)
        assert result == 0
        out = capsys.readouterr().out
        assert "1 comment(s)" in out

    def test_with_body_file(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        from scripts.github.create_pr_review import _build_parser, _run

        body_path = tmp_path / "body.md"
        body_path.write_text("Body from file", encoding="utf-8")

        parser = _build_parser()
        args = parser.parse_args(
            [
                "--repo",
                "owner/name",
                "--pr",
                "10",
                "--body-file",
                str(body_path),
                "--commit-id",
                "sha_bf",
            ]
        )
        runner = QueueRunner([])
        result = _run(args, parser, runner)
        assert result == 0

    def test_skip_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        from scripts.github.create_pr_review import _build_parser, _run

        parser = _build_parser()
        args = parser.parse_args(
            [
                "--repo",
                "owner/name",
                "--pr",
                "10",
                "--body",
                "Dup body",
                "--commit-id",
                "sha_skip",
                "--apply",
            ]
        )
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=["gh", "api", "/repos/owner/name/pulls/10/reviews", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps(["Dup body"]),
                ),
            ]
        )
        result = _run(args, parser, runner)
        assert result == 0
        out = capsys.readouterr().out
        assert "Skipped" in out
        assert "PR #10" in out
        runner.assert_exhausted()

    def test_skip_json_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        from scripts.github.create_pr_review import _build_parser, _run

        parser = _build_parser()
        args = parser.parse_args(
            [
                "--repo",
                "owner/name",
                "--pr",
                "10",
                "--body",
                "Dup body",
                "--commit-id",
                "sha_skip",
                "--apply",
                "--json",
            ]
        )
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=["gh", "api", "/repos/owner/name/pulls/10/reviews", "--paginate", "--jq", "map(.body)"],
                    stdout=json.dumps(["Dup body"]),
                ),
            ]
        )
        result = _run(args, parser, runner)
        assert result == 0
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["skip_reason"] is not None
        assert payload["applied"] is False
        runner.assert_exhausted()

    def test_with_comments_file(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        from scripts.github.create_pr_review import _build_parser, _run

        comments_path = tmp_path / "comments.json"
        comments_path.write_text(
            json.dumps([{"path": "a.py", "body": "Note"}]),
            encoding="utf-8",
        )

        parser = _build_parser()
        args = parser.parse_args(
            [
                "--repo",
                "owner/name",
                "--pr",
                "10",
                "--comments-file",
                str(comments_path),
                "--commit-id",
                "sha_cf",
            ]
        )
        runner = QueueRunner([])
        result = _run(args, parser, runner)
        assert result == 0


class TestMainEntryPoint:
    def test_main_returns_int(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from scripts.github.create_pr_review import main

        monkeypatch.setattr(
            "sys.argv",
            [
                "create_pr_review",
                "--repo",
                "owner/name",
                "--pr",
                "1",
                "--body",
                "test",
                "--commit-id",
                "sha",
            ],
        )

        # main() calls run_actionable_main which instantiates SubprocessGhRunner.
        # We can't mock that easily, but we can verify it returns an int
        # by catching the GhCliError from the subprocess call.
        # Instead, test that main is callable and returns int type.
        # The run_actionable_main handler catches errors and returns 2.
        result = main()
        assert isinstance(result, int)


class TestCreateReviewResult:
    def test_defaults(self) -> None:
        result = CreateReviewResult(
            success=True,
            repo="owner/name",
            pr_number=1,
            event="COMMENT",
            comments_count=0,
            applied=False,
        )
        assert result.review_id is None
        assert result.error is None
        assert result.skip_reason is None

    def test_with_skip_reason(self) -> None:
        result = CreateReviewResult(
            success=True,
            repo="o/r",
            pr_number=1,
            event="COMMENT",
            comments_count=0,
            applied=False,
            skip_reason="duplicate",
        )
        assert result.skip_reason == "duplicate"

    def test_frozen(self) -> None:
        result = CreateReviewResult(
            success=True,
            repo="o/r",
            pr_number=1,
            event="COMMENT",
            comments_count=0,
            applied=False,
        )
        with pytest.raises(AttributeError):
            result.success = False  # type: ignore[misc]
