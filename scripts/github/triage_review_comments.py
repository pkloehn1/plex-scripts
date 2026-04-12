#!/usr/bin/env python3
"""Triage PR review comments in a single flow: list, reply, and resolve.

Consolidates the list-reply-resolve workflow into one or two invocations:

1. List unresolved comments matching filters (no --replies-json):
    Shows comments so the caller can prepare responses.

2. Reply and resolve (with --replies-json):
    Posts replies and resolves threads for each specified comment.

Individual helpers (list_pr_review_comments_filtered,
reply_and_resolve_review_comment) remain available for troubleshooting.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Any

from scripts.github.cli_utils import casefold_nonempty_str, normalize_nonempty_str
from scripts.github.gh_cli import (
    ActionableArgumentParser,
    GhRunner,
    active_pr_number,
    current_repo,
    run_actionable_main,
)
from scripts.github.list_pr_review_comments import list_review_comments
from scripts.github.list_pr_review_comments_filtered import _matches_filters
from scripts.github.reply_and_resolve_review_comment import (
    post_reply_idempotent,
    resolve_review_thread,
)


@dataclass(frozen=True)
class ReplySpec:
    """A single reply-and-resolve instruction."""

    comment_id: int
    body: str


def parse_replies_json(raw: str) -> list[ReplySpec]:
    """Parse --replies-json into a list of ReplySpec.

    Expected format: [{"comment_id": 123, "body": "Fixed."}]
    """
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("--replies-json must be a JSON array")

    specs: list[ReplySpec] = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("Each element in --replies-json must be an object")
        comment_id = item.get("comment_id")
        body = item.get("body")
        if not isinstance(comment_id, int):
            raise ValueError("Each element must have an integer 'comment_id'")
        if not isinstance(body, str) or not body.strip():
            raise ValueError("Each element must have a non-empty string 'body'")
        specs.append(ReplySpec(comment_id=comment_id, body=body))
    return specs


def list_filtered_comments(
    *,
    runner: GhRunner,
    repo: str,
    pr_number: int,
    author_substring: str | None,
    contains: str | None,
    path: str | None,
) -> list[dict[str, Any]]:
    """List PR review comments matching the given filters."""
    comments = list_review_comments(runner=runner, repo=repo, pr_number=pr_number)
    return [
        comment
        for comment in comments
        if _matches_filters(
            comment,
            author_substring=author_substring,
            contains=contains,
            path=path,
        )
    ]


def triage_comments(
    *,
    runner: GhRunner,
    repo: str,
    pr_number: int,
    author_substring: str | None = None,
    contains: str | None = None,
    path: str | None = None,
    replies: list[ReplySpec] | None = None,
) -> dict[str, Any]:
    """Run the triage flow: list comments and optionally reply+resolve.

    Returns a result dict with comment listing and reply outcomes.
    """
    filtered = list_filtered_comments(
        runner=runner,
        repo=repo,
        pr_number=pr_number,
        author_substring=author_substring,
        contains=contains,
        path=path,
    )

    result: dict[str, Any] = {
        "repo": repo,
        "pr": pr_number,
        "filters": {
            "author_substring": author_substring,
            "contains": contains,
            "path": path,
        },
        "comments_count": len(filtered),
        "comments": filtered,
    }

    if not replies:
        result["action"] = "list_only"
        return result

    reply_results: list[dict[str, Any]] = []
    for spec in replies:
        reply_result: dict[str, Any] = {
            "comment_id": spec.comment_id,
            "body": spec.body,
        }
        reply_payload, skipped = post_reply_idempotent(
            runner=runner,
            repo=repo,
            pr_number=pr_number,
            comment_id=spec.comment_id,
            body=spec.body,
        )
        reply_result["reply_id"] = reply_payload.get("id") if isinstance(reply_payload, dict) else None
        reply_result["reply_skipped"] = skipped

        resolved = resolve_review_thread(
            runner=runner,
            repo=repo,
            pr_number=pr_number,
            comment_id=spec.comment_id,
        )
        reply_result["resolved"] = resolved
        reply_results.append(reply_result)

    result["action"] = "reply_and_resolve"
    result["reply_results"] = reply_results
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = ActionableArgumentParser(description="Triage PR review comments: list, reply, and resolve in one flow.")
    parser.add_argument("--repo", default=None, help="Repo owner/name (default: auto-detect)")
    parser.add_argument("--pr", type=int, default=None, help="PR number (default: active PR)")
    parser.add_argument(
        "--author-substring",
        default=None,
        help="Case-insensitive substring match against comment author login.",
    )
    parser.add_argument(
        "--contains",
        default=None,
        help="Case-insensitive substring match against comment body.",
    )
    parser.add_argument("--path", default=None, help="Only include comments on this exact file path.")
    parser.add_argument(
        "--replies-json",
        default=None,
        help=(
            'JSON array of replies: [{"comment_id": 123, "body": "Fixed."}]. '
            "If omitted, lists comments without replying."
        ),
    )
    return parser


def _run(
    args: argparse.Namespace,
    _parser: argparse.ArgumentParser,
    runner: GhRunner,
) -> int:
    repo = args.repo or current_repo(runner)
    pr_number = args.pr or active_pr_number(runner)

    author_substring = casefold_nonempty_str(args.author_substring)
    contains = casefold_nonempty_str(args.contains)
    path = normalize_nonempty_str(args.path)

    replies: list[ReplySpec] | None = None
    if args.replies_json:
        replies = parse_replies_json(args.replies_json)

    result = triage_comments(
        runner=runner,
        repo=repo,
        pr_number=pr_number,
        author_substring=author_substring,
        contains=contains,
        path=path,
        replies=replies,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def main() -> int:
    return run_actionable_main(
        build_parser=_build_parser,
        handler=_run,
        examples=[
            "python -m scripts.github.triage_review_comments --repo owner/name --pr 123",
            ("python -m scripts.github.triage_review_comments --repo owner/name --pr 123 --author-substring copilot"),
            (
                "python -m scripts.github.triage_review_comments --repo owner/name --pr 123 "
                '--replies-json \'[{"comment_id": 456, "body": "Fixed."}]\''
            ),
        ],
        see_also=["scripts/github/README.md"],
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
