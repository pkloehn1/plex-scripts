#!/usr/bin/env python3
r"""Create a PR review with inline comments in a single atomic API call.

Avoids the two-step PENDING-then-submit pattern that causes duplicate
review threads (Issue #257).

Usage::

    python -m scripts.github.create_pr_review \
        --repo owner/name --pr 42 \
        --body "Review summary" \
        --event COMMENT \
        --comments-json '[{"path": "file.py", "line": 10, "body": "Fix this"}]' \
        --apply
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from scripts.github.cli_utils import read_optional_text, resolve_repo_pr
from scripts.github.gh_cli import (
    ActionableArgumentParser,
    GhRunner,
    parse_repo,
    run_actionable_main,
    run_json,
    run_text,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_EVENTS = frozenset({"COMMENT", "APPROVE", "REQUEST_CHANGES"})
_VALID_SIDES = frozenset({"LEFT", "RIGHT"})

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReviewComment:
    """A single inline comment to include in the review."""

    path: str
    body: str
    line: int | None = None
    side: str | None = None
    start_line: int | None = None


@dataclass(frozen=True)
class CreateReviewResult:
    """Result of the create-review operation."""

    success: bool
    repo: str
    pr_number: int
    event: str
    comments_count: int
    applied: bool
    review_id: int | None = None
    error: str | None = None
    skip_reason: str | None = None


# ---------------------------------------------------------------------------
# Input parsing
# ---------------------------------------------------------------------------


def parse_comments(raw: str) -> list[ReviewComment]:
    """Parse a JSON array of comment objects into ReviewComment instances.

    Required fields per comment: ``path``, ``body``.
    Optional fields: ``line``, ``side``, ``start_line``.
    """
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("Comments JSON must be an array")

    comments: list[ReviewComment] = []
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"Comment at index {idx} must be an object")

        path = item.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ValueError(f"Comment at index {idx}: 'path' is required and must be non-empty")

        body = item.get("body")
        if not isinstance(body, str) or not body.strip():
            raise ValueError(f"Comment at index {idx}: 'body' is required and must be non-empty")

        comments.append(
            ReviewComment(
                path=path,
                body=body,
                line=item.get("line"),
                side=item.get("side"),
                start_line=item.get("start_line"),
            )
        )

    return comments


def read_comments_input(
    *,
    comments_json: str | None,
    comments_file: Path | None,
) -> list[ReviewComment] | None:
    """Read comments from ``--comments-json`` or ``--comments-file``.

    Returns ``None`` if neither is provided.
    """
    if comments_json is not None and comments_file is not None:
        raise ValueError("Provide only one of --comments-json or --comments-file")

    if comments_file is not None:
        raw = comments_file.read_text(encoding="utf-8")
        return parse_comments(raw)

    if comments_json is not None:
        return parse_comments(comments_json)

    return None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_comment(idx: int, comment: ReviewComment) -> None:
    """Validate a single inline comment."""
    if not comment.path.strip():
        raise ValueError(f"Comment at index {idx}: 'path' must be non-empty")
    if not comment.body.strip():
        raise ValueError(f"Comment at index {idx}: 'body' must be non-empty")
    if comment.side is not None and comment.side not in _VALID_SIDES:
        raise ValueError(f"Comment at index {idx}: 'side' must be LEFT or RIGHT, got {comment.side!r}")
    if comment.start_line is not None and comment.line is None:
        raise ValueError(f"Comment at index {idx}: 'start_line' requires 'line' to be set")


def validate_review_inputs(
    *,
    event: str,
    body: str | None,
    comments: list[ReviewComment] | None,
) -> None:
    """Validate review inputs before calling the API."""
    if event not in _VALID_EVENTS:
        raise ValueError(f"Invalid event {event!r}. Allowed: {sorted(_VALID_EVENTS)}")

    has_body = body is not None and body.strip()
    has_comments = comments is not None and len(comments) > 0
    if not has_body and not has_comments:
        raise ValueError("At least one of --body or --comments-json/--comments-file is required")

    if comments:
        for idx, comment in enumerate(comments):
            _validate_comment(idx, comment)


# ---------------------------------------------------------------------------
# Payload construction
# ---------------------------------------------------------------------------


def build_review_payload(
    *,
    commit_id: str | None,
    body: str | None,
    event: str,
    comments: list[ReviewComment] | None,
) -> dict[str, Any]:
    """Build the JSON payload for ``POST /repos/{owner}/{name}/pulls/{pr}/reviews``."""
    payload: dict[str, Any] = {"event": event}

    if commit_id is not None:
        payload["commit_id"] = commit_id

    if body is not None:
        payload["body"] = body

    if comments:
        payload["comments"] = []
        for comment in comments:
            entry: dict[str, Any] = {"path": comment.path, "body": comment.body}
            if comment.line is not None:
                entry["line"] = comment.line
            if comment.side is not None:
                entry["side"] = comment.side
            if comment.start_line is not None:
                entry["start_line"] = comment.start_line
            payload["comments"].append(entry)

    return payload


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_body(text: str) -> str:
    """Collapse all whitespace runs into a single space and strip."""
    return _WHITESPACE_RE.sub(" ", text).strip()


def _fetch_existing_review_bodies(
    *,
    runner: GhRunner,
    repo: str,
    pr_number: int,
) -> list[str]:
    """Fetch body text from all existing PR reviews."""
    owner, name = parse_repo(repo)
    bodies = run_json(
        runner,
        [
            "gh",
            "api",
            f"/repos/{owner}/{name}/pulls/{pr_number}/reviews",
            "--paginate",
            "--jq",
            "map(.body)",
        ],
    )
    if not isinstance(bodies, list):
        return []
    return [body for body in bodies if isinstance(body, str) and body]


def _fetch_existing_comment_bodies(
    *,
    runner: GhRunner,
    repo: str,
    pr_number: int,
) -> list[str]:
    """Fetch body text from all existing issue comments on a PR."""
    owner, name = parse_repo(repo)
    bodies = run_json(
        runner,
        [
            "gh",
            "api",
            f"/repos/{owner}/{name}/issues/{pr_number}/comments",
            "--paginate",
            "--jq",
            "map(.body)",
        ],
    )
    if not isinstance(bodies, list):
        return []
    return [body for body in bodies if isinstance(body, str) and body]


def _content_already_exists(
    *,
    runner: GhRunner,
    repo: str,
    pr_number: int,
    body: str,
) -> str | None:
    """Check whether *body* already exists in PR reviews or issue comments.

    Returns a human-readable skip reason if a duplicate is found, or ``None``.
    """
    normalized = _normalize_body(body)
    if not normalized:
        return None

    for existing in _fetch_existing_review_bodies(runner=runner, repo=repo, pr_number=pr_number):
        if _normalize_body(existing) == normalized:
            return "identical content already exists in a PR review"

    for existing in _fetch_existing_comment_bodies(runner=runner, repo=repo, pr_number=pr_number):
        if _normalize_body(existing) == normalized:
            return "identical content already exists in an issue comment"

    return None


# ---------------------------------------------------------------------------
# API interaction
# ---------------------------------------------------------------------------


def fetch_pr_head_sha(
    *,
    runner: GhRunner,
    repo: str,
    pr_number: int,
) -> str:
    """Fetch the HEAD commit SHA of a PR."""
    owner, name = parse_repo(repo)
    sha = run_text(
        runner,
        ["gh", "api", f"/repos/{owner}/{name}/pulls/{pr_number}", "--jq", ".head.sha"],
    ).strip()
    if not sha:
        raise ValueError(f"Unable to determine HEAD SHA for PR #{pr_number}")
    return sha


def create_pr_review(
    *,
    runner: GhRunner,
    repo: str,
    pr_number: int,
    event: str,
    body: str | None = None,
    comments: list[ReviewComment] | None = None,
    commit_id: str | None = None,
    apply: bool = False,
) -> CreateReviewResult:
    """Create a PR review in a single atomic API call.

    When ``apply=False`` (default), validates inputs and returns a dry-run
    result without calling the API.
    """
    validate_review_inputs(event=event, body=body, comments=comments)

    comments_count = len(comments) if comments else 0

    if not apply:
        return CreateReviewResult(
            success=True,
            repo=repo,
            pr_number=pr_number,
            event=event,
            comments_count=comments_count,
            applied=False,
        )

    if body:
        skip_reason = _content_already_exists(runner=runner, repo=repo, pr_number=pr_number, body=body)
        if skip_reason is not None:
            if not comments:
                return CreateReviewResult(
                    success=True,
                    repo=repo,
                    pr_number=pr_number,
                    event=event,
                    comments_count=comments_count,
                    applied=False,
                    skip_reason=skip_reason,
                )
            body = None

    if commit_id is None:
        commit_id = fetch_pr_head_sha(runner=runner, repo=repo, pr_number=pr_number)

    payload = build_review_payload(
        commit_id=commit_id,
        body=body,
        event=event,
        comments=comments,
    )

    owner, name = parse_repo(repo)
    response = run_json(
        runner,
        [
            "gh",
            "api",
            "--method",
            "POST",
            f"/repos/{owner}/{name}/pulls/{pr_number}/reviews",
            "--input",
            "-",
        ],
        input_text=json.dumps(payload),
    )

    review_id = response.get("id") if isinstance(response, dict) else None

    return CreateReviewResult(
        success=True,
        repo=repo,
        pr_number=pr_number,
        event=event,
        comments_count=comments_count,
        applied=True,
        review_id=review_id,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = ActionableArgumentParser(
        description="Create a PR review with inline comments in a single atomic API call.",
    )
    parser.add_argument("--repo", default=None, help="Repo owner/name (default: auto-detect)")
    parser.add_argument("--pr", type=int, default=None, help="PR number (default: active PR)")
    parser.add_argument(
        "--event",
        choices=sorted(_VALID_EVENTS),
        default="COMMENT",
        help="Review event type (default: COMMENT)",
    )
    parser.add_argument("--body", default=None, help="Review summary body text")
    parser.add_argument(
        "--body-file",
        type=Path,
        default=None,
        help="Path to UTF-8 file containing review summary body",
    )
    parser.add_argument(
        "--comments-json",
        default=None,
        help='JSON array of inline comments: [{"path": "file.py", "line": 42, "body": "text"}]',
    )
    parser.add_argument(
        "--comments-file",
        type=Path,
        default=None,
        help="Path to UTF-8 JSON file containing inline comments array",
    )
    parser.add_argument(
        "--commit-id",
        default=None,
        help="Commit SHA to attach the review to (default: PR HEAD)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually create the review (default: dry-run)",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    return parser


def _run(
    args: argparse.Namespace,
    _parser: argparse.ArgumentParser,
    runner: GhRunner,
) -> int:
    resolved = resolve_repo_pr(args, runner)
    body = read_optional_text(text=args.body, path=args.body_file)
    comments = read_comments_input(
        comments_json=args.comments_json,
        comments_file=getattr(args, "comments_file", None),
    )

    result = create_pr_review(
        runner=runner,
        repo=resolved.repo,
        pr_number=resolved.pr_number,
        event=args.event,
        body=body,
        comments=comments,
        commit_id=args.commit_id,
        apply=bool(args.apply),
    )

    if args.json:
        print(json.dumps(asdict(result), indent=2, sort_keys=True))
    elif result.skip_reason:
        print(f"Skipped: {result.skip_reason} (PR #{resolved.pr_number}).")
    elif result.applied:
        print(f"Created review on PR #{resolved.pr_number} ({result.event}, {result.comments_count} comment(s)).")
    else:
        print(
            f"Dry-run: would create review on PR #{resolved.pr_number}"
            f" ({result.event}, {result.comments_count} comment(s))."
            f" Use --apply to submit."
        )

    return 0


def main() -> int:
    """Entry point for ``python -m scripts.github.create_pr_review``."""
    return run_actionable_main(
        build_parser=_build_parser,
        handler=_run,
        examples=[
            (
                ".venv/bin/python -m scripts.github.create_pr_review"
                " --repo owner/name --pr 42 --body 'Looks good' --event APPROVE --apply"
            ),
            (
                ".venv/bin/python -m scripts.github.create_pr_review"
                " --repo owner/name --pr 42 --event COMMENT"
                ' --comments-json \'[{"path": "file.py", "line": 10, "body": "Fix this"}]\''
                " --apply"
            ),
        ],
        see_also=["scripts/github/README.md"],
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
