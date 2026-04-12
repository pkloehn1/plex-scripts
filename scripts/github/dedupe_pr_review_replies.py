#!/usr/bin/env python3
"""Delete duplicate PR review reply comments created by automation.

Scope:
- This targets PR *review comments* (inline diff comments), not issue comments.
- It only deletes comments authored by the current authenticated user (or an
    explicit --author), to avoid touching reviewer comments.

Definition of duplicate:
- Same in_reply_to (same parent review comment)
- Same body text

Default behavior is dry-run. Use --apply to delete.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from scripts.github.gh_cli import (
    ActionableArgumentParser,
    GhCliError,
    GhRunner,
    SubprocessGhRunner,
    active_pr_number,
    current_login,
    current_repo,
    parse_repo,
    print_actionable_cli_error,
    run_json,
)


@dataclass(frozen=True)
class ReviewReply:
    comment_id: int
    in_reply_to: int
    body: str
    author: str
    created_at: str


def _build_parser() -> argparse.ArgumentParser:
    parser = ActionableArgumentParser(description="Deduplicate PR review reply comments (safe-by-default).")
    parser.add_argument(
        "--repo",
        help="GitHub repo (owner/name). Default: auto-detect via gh.",
    )
    parser.add_argument(
        "--pr",
        type=int,
        help="PR number. Default: active PR for current branch.",
    )
    parser.add_argument(
        "--author",
        help=("Only consider replies authored by this login. Default: current gh user."),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete duplicates (default: dry-run).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON result to stdout.",
    )
    return parser


def _parse_review_reply(*, payload: Any, author: str) -> ReviewReply | None:
    if not isinstance(payload, dict):
        return None

    comment_id = payload.get("id")
    in_reply_to = payload.get("in_reply_to")
    if in_reply_to is None:
        # GitHub REST API uses `in_reply_to_id`.
        in_reply_to = payload.get("in_reply_to_id")
    body = payload.get("body")
    created_at = payload.get("created_at")
    user = payload.get("user")
    login = user.get("login") if isinstance(user, dict) else None

    if not isinstance(comment_id, int) or comment_id <= 0:
        return None
    if not isinstance(in_reply_to, int) or in_reply_to <= 0:
        return None
    if not isinstance(body, str):
        return None
    if not isinstance(created_at, str):
        return None
    if not isinstance(login, str) or login.strip() != author:
        return None

    return ReviewReply(
        comment_id=comment_id,
        in_reply_to=in_reply_to,
        body=body,
        author=login.strip(),
        created_at=created_at,
    )


def list_pr_review_replies(*, runner: GhRunner, repo: str, pr_number: int, author: str) -> list[ReviewReply]:
    owner, name = parse_repo(repo)

    comments = run_json(
        runner,
        [
            "gh",
            "api",
            f"/repos/{owner}/{name}/pulls/{pr_number}/comments",
            "--paginate",
        ],
    )

    if not isinstance(comments, list):
        raise ValueError("Unexpected PR review comments payload")

    out: list[ReviewReply] = []
    for comment in comments:
        reply = _parse_review_reply(payload=comment, author=author)
        if reply is not None:
            out.append(reply)
    return out


def _sort_key(reply: ReviewReply) -> tuple[int, datetime, int]:
    # Prefer created_at ordering; break ties with comment id.
    try:
        created = datetime.fromisoformat(reply.created_at.replace("Z", "+00:00"))
    except ValueError:
        created = datetime.min
    return (reply.in_reply_to, created, reply.comment_id)


def find_duplicate_reply_ids(replies: list[ReviewReply]) -> list[int]:
    """Return comment IDs to delete (keeps earliest per duplicate group)."""
    sorted_replies = sorted(replies, key=_sort_key)

    seen: set[tuple[int, str]] = set()
    delete_ids: list[int] = []

    for reply in sorted_replies:
        key = (reply.in_reply_to, reply.body)
        if key in seen:
            delete_ids.append(reply.comment_id)
            continue
        seen.add(key)

    return delete_ids


def delete_pr_review_comment(*, runner: GhRunner, repo: str, comment_id: int) -> None:
    owner, name = parse_repo(repo)
    run_json(
        runner,
        [
            "gh",
            "api",
            "--method",
            "DELETE",
            f"/repos/{owner}/{name}/pulls/comments/{comment_id}",
        ],
    )


def dedupe_pr_review_replies(
    *, runner: GhRunner, repo: str, pr_number: int, author: str, apply: bool
) -> dict[str, Any]:
    replies = list_pr_review_replies(
        runner=runner,
        repo=repo,
        pr_number=pr_number,
        author=author,
    )

    delete_ids = find_duplicate_reply_ids(replies)

    if apply:
        for comment_id in delete_ids:
            delete_pr_review_comment(runner=runner, repo=repo, comment_id=comment_id)

    return {
        "repo": repo,
        "pr": pr_number,
        "author": author,
        "apply": apply,
        "total_replies_considered": len(replies),
        "duplicate_reply_ids": delete_ids,
        "deleted_count": len(delete_ids) if apply else 0,
    }


def main() -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args()
        runner = SubprocessGhRunner()

        repo = args.repo or current_repo(runner)
        pr_number = args.pr or active_pr_number(runner)
        author = args.author or current_login(runner)

        result = dedupe_pr_review_replies(
            runner=runner,
            repo=repo,
            pr_number=pr_number,
            author=author,
            apply=bool(args.apply),
        )

        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            if result["duplicate_reply_ids"]:
                print(
                    f"Found {len(result['duplicate_reply_ids'])} duplicate review reply comment(s) for PR #{pr_number} (author={author})."
                )
                if args.apply:
                    print("Deleted duplicates.")
                else:
                    print("Dry-run only (use --apply to delete).")
            else:
                print(f"No duplicate review reply comments found for PR #{pr_number} (author={author}).")

        return 0
    except (GhCliError, ValueError) as exc:
        print_actionable_cli_error(
            exc,
            parser=parser,
            examples=[
                "python -m scripts.github.dedupe_pr_review_replies --repo owner/name --pr 123",
                "python -m scripts.github.dedupe_pr_review_replies --repo owner/name --pr 123 --apply",
            ],
            see_also=["scripts/github/README.md"],
        )
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
