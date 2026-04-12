#!/usr/bin/env python3
"""List PR review comments with common filters (stable JSON output).

Use case:
- Produce a deterministic list of PR review comments to be handled by the repo's
    reply/resolve automation, regardless of author (Copilot, Cursor, humans, etc.).

Filters:
- --author-substring: case-insensitive substring match against author login
    (example: "copilot", "cursor")
- --contains: case-insensitive substring match against comment body
- --path: exact match on file path

This script is read-only.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from scripts.github.cli_utils import casefold_nonempty_str, normalize_nonempty_str
from scripts.github.gh_cli import (
    ActionableArgumentParser,
    GhCliError,
    SubprocessGhRunner,
    active_pr_number,
    current_repo,
    print_actionable_cli_error,
)
from scripts.github.list_pr_review_comments import list_review_comments


def _build_parser() -> argparse.ArgumentParser:
    parser = ActionableArgumentParser(description="List PR review comments with filters.")
    parser.add_argument("--repo", default=None, help="Repo owner/name (default: auto-detect)")
    parser.add_argument("--pr", type=int, default=None, help="PR number (default: active PR)")
    parser.add_argument(
        "--author-substring",
        default=None,
        help="Case-insensitive substring match against comment author login (e.g., copilot, cursor).",
    )
    parser.add_argument(
        "--contains",
        default=None,
        help="Case-insensitive substring match against comment body.",
    )
    parser.add_argument(
        "--path",
        default=None,
        help="Only include comments on this exact file path.",
    )
    return parser


def _matches_filters(
    comment: dict[str, Any],
    *,
    author_substring: str | None,
    contains: str | None,
    path: str | None,
) -> bool:
    if author_substring:
        author = comment.get("author")
        author_cf = author.casefold() if isinstance(author, str) else ""
        if author_substring not in author_cf:
            return False

    if contains:
        body = comment.get("body")
        body_cf = body.casefold() if isinstance(body, str) else ""
        if contains not in body_cf:
            return False

    if path:
        cpath = comment.get("path")
        if not isinstance(cpath, str) or cpath != path:
            return False

    return True


def main() -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args()
        runner = SubprocessGhRunner()

        author_substring = casefold_nonempty_str(args.author_substring)
        contains = casefold_nonempty_str(args.contains)
        path = normalize_nonempty_str(args.path)

        repo = args.repo or current_repo(runner)
        pr_number = args.pr or active_pr_number(runner)

        comments = list_review_comments(runner=runner, repo=repo, pr_number=pr_number)
        filtered = [
            comment
            for comment in comments
            if _matches_filters(comment, author_substring=author_substring, contains=contains, path=path)
        ]

        print(
            json.dumps(
                {
                    "repo": repo,
                    "pr": pr_number,
                    "filters": {
                        "author_substring": args.author_substring,
                        "contains": args.contains,
                        "path": args.path,
                    },
                    "count": len(filtered),
                    "comments": filtered,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except (GhCliError, ValueError) as exc:
        print_actionable_cli_error(
            exc,
            parser=parser,
            examples=[
                "python -m scripts.github.list_pr_review_comments_filtered --repo owner/name --pr 123",
                "python -m scripts.github.list_pr_review_comments_filtered --repo owner/name --pr 123 --author-substring copilot",
                'python -m scripts.github.list_pr_review_comments_filtered --repo owner/name --pr 123 --contains "please"',
            ],
            see_also=["scripts/github/README.md"],
        )
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
