#!/usr/bin/env python3
"""List unresolved PR review threads (offline-friendly JSON output).

Primary use case:
- Pull all unresolved review comment threads for the PR associated with the
    current branch (or an explicitly provided PR number).

This script intentionally does not attempt to resolve anything.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from typing import Any

from scripts.github.cli_utils import casefold_nonempty_str, normalize_nonempty_str
from scripts.github.gh_cli import (
    ActionableArgumentParser,
    GhCliError,
    GhRunner,
    SubprocessGhRunner,
    active_pr_number,
    as_dict,
    as_list,
    current_repo,
    parse_repo,
    print_actionable_cli_error,
    run_json,
)


@dataclass(frozen=True)
class ReviewComment:
    database_id: int
    node_id: str
    author: str | None
    body: str
    url: str


@dataclass(frozen=True)
class ReviewThread:
    thread_id: str
    path: str | None
    line: int | None
    is_resolved: bool
    comments: list[ReviewComment]


_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $after: String) {
    repository(owner: $owner, name: $name) {
        pullRequest(number: $number) {
            reviewThreads(first: 100, after: $after) {
                nodes {
                    id
                    isResolved
                    path
                    line
                    comments(first: 50) {
                        nodes {
                            databaseId
                            id
                            body
                            url
                            author { login }
                        }
                    }
                }
                pageInfo { hasNextPage endCursor }
            }
        }
    }
}
""".strip()


def _parse_comment_node(node: Any) -> ReviewComment | None:
    data = as_dict(node)
    database_id = data.get("databaseId")
    node_id = data.get("id")

    if not isinstance(database_id, int):
        return None
    if not isinstance(node_id, str):
        return None

    body = data.get("body")
    url = data.get("url")
    author_login = as_dict(data.get("author")).get("login")

    author: str | None
    if isinstance(author_login, str) and author_login.strip():
        author = author_login.strip()
    else:
        author = None

    return ReviewComment(
        database_id=database_id,
        node_id=node_id,
        author=author,
        body=body if isinstance(body, str) else "",
        url=url if isinstance(url, str) else "",
    )


def _parse_thread_node(node: Any) -> ReviewThread | None:
    data = as_dict(node)
    thread_id = data.get("id")
    if not isinstance(thread_id, str):
        return None

    comments_payload = as_dict(data.get("comments"))
    comment_nodes = as_list(comments_payload.get("nodes"))
    comments = [comment for comment in (_parse_comment_node(node) for node in comment_nodes) if comment]

    path = data.get("path")
    line = data.get("line")

    return ReviewThread(
        thread_id=thread_id,
        path=path if isinstance(path, str) else None,
        line=line if isinstance(line, int) else None,
        is_resolved=bool(data.get("isResolved")),
        comments=comments,
    )


def _end_cursor_if_has_next(page_info: Any) -> str | None:
    info = as_dict(page_info)
    if info.get("hasNextPage") is not True:
        return None
    cursor = info.get("endCursor")
    if isinstance(cursor, str) and cursor.strip():
        return cursor
    return None


def _parse_threads(payload: dict[str, Any]) -> tuple[list[ReviewThread], str | None]:
    data = as_dict(payload.get("data"))
    repo = as_dict(data.get("repository"))
    pull_request = as_dict(repo.get("pullRequest"))
    threads = as_dict(pull_request.get("reviewThreads"))

    nodes = as_list(threads.get("nodes"))
    parsed_threads = [thread for thread in (_parse_thread_node(node) for node in nodes) if thread]
    cursor = _end_cursor_if_has_next(threads.get("pageInfo"))
    return parsed_threads, cursor


def list_unresolved_review_threads(*, repo: str, pr_number: int, runner: GhRunner) -> list[ReviewThread]:
    owner, name = parse_repo(repo)

    after: str | None = None
    all_threads: list[ReviewThread] = []
    while True:
        payload = run_json(
            runner,
            [
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
                *(["-f", f"after={after}"] if after else []),
            ],
        )
        if not isinstance(payload, dict):
            raise ValueError("Unexpected GraphQL response (expected object)")

        threads, after = _parse_threads(payload)
        all_threads.extend([thread for thread in threads if not thread.is_resolved])

        if not after:
            break

    return all_threads


def _thread_matches_path(thread: ReviewThread, path_filter: str | None) -> bool:
    if not path_filter:
        return True
    if not thread.path:
        return False
    if thread.path == path_filter:
        return True
    return thread.path.endswith(path_filter)


def _thread_contains_text(thread: ReviewThread, needle: str | None) -> bool:
    if not needle:
        return True
    return any(needle in comment.body.casefold() for comment in thread.comments)


def _thread_has_author(thread: ReviewThread, author_filter: str | None) -> bool:
    if not author_filter:
        return True
    return any(comment.author == author_filter for comment in thread.comments)


def _thread_matches_filters(
    thread: ReviewThread,
    *,
    path_filter: str | None,
    line_filter: int | None,
    needle: str | None,
    author_filter: str | None,
) -> bool:
    if not _thread_matches_path(thread, path_filter):
        return False
    if line_filter is not None and thread.line != line_filter:
        return False
    if not _thread_contains_text(thread, needle):
        return False
    return _thread_has_author(thread, author_filter)


def filter_review_threads(
    threads: list[ReviewThread],
    *,
    path: str | None = None,
    line: int | None = None,
    contains: str | None = None,
    author: str | None = None,
) -> list[ReviewThread]:
    """Filter review threads to help locate a specific comment quickly.

    This is intended to keep scripts usable in CI/automation contexts where
    selecting the correct thread by file and line is important.

    Args:
        threads: Unresolved review threads.
        path: File path filter. Matches exact or suffix (e.g., docker-compose.yml).
        line: Exact line number filter.
        contains: Case-insensitive substring match against any comment body.
        author: Exact author login match against any comment's author.

    Returns:
        Filtered list of threads.
    """
    path_filter = normalize_nonempty_str(path)
    author_filter = normalize_nonempty_str(author)
    needle = casefold_nonempty_str(contains)

    return [
        thread
        for thread in threads
        if _thread_matches_filters(
            thread,
            path_filter=path_filter,
            line_filter=line,
            needle=needle,
            author_filter=author_filter,
        )
    ]


def _build_parser() -> argparse.ArgumentParser:
    parser = ActionableArgumentParser(description="List unresolved PR review threads.")
    parser.add_argument(
        "--repo",
        help="GitHub repo (owner/name). Default: auto-detect via gh.",
        default=None,
    )
    parser.add_argument(
        "--pr",
        type=int,
        default=None,
        help="PR number. Default: active PR for current branch.",
    )
    parser.add_argument(
        "--format",
        choices=["json"],
        default="json",
        help="Output format (default: json).",
    )

    parser.add_argument(
        "--path",
        default=None,
        help=(
            "Filter by file path (exact or suffix match). "
            "Example: --path stacks/<stack>/docker-compose.yml or --path docker-compose.yml"
        ),
    )
    parser.add_argument(
        "--line",
        type=int,
        default=None,
        help="Filter by exact line number (thread line).",
    )
    parser.add_argument(
        "--contains",
        default=None,
        help="Filter by case-insensitive substring match against comment bodies.",
    )
    parser.add_argument(
        "--author",
        default=None,
        help="Filter by exact GitHub login of any comment author in the thread.",
    )
    parser.add_argument(
        "--require-one",
        action="store_true",
        help="Exit non-zero unless exactly one thread matches the filters.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    runner = SubprocessGhRunner()

    try:
        repo = args.repo or current_repo(runner)
        pr_number = args.pr or active_pr_number(runner)

        threads = list_unresolved_review_threads(repo=repo, pr_number=pr_number, runner=runner)
        filtered = filter_review_threads(
            threads,
            path=args.path,
            line=args.line,
            contains=args.contains,
            author=args.author,
        )

        exit_code = 0
        if args.require_one and len(filtered) != 1:
            exit_code = 2
            print(
                f"Expected exactly 1 matching thread, found {len(filtered)}.",
                file=sys.stderr,
            )
        print(
            json.dumps(
                {
                    "repo": repo,
                    "pr": pr_number,
                    "filters": {
                        "path": args.path,
                        "line": args.line,
                        "contains": args.contains,
                        "author": args.author,
                        "require_one": bool(args.require_one),
                    },
                    "unresolved_threads": [asdict(thread) for thread in filtered],
                    "count": len(filtered),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return exit_code
    except (GhCliError, ValueError) as err:
        print_actionable_cli_error(
            err,
            parser=parser,
            examples=[
                "python -m scripts.github.list_unresolved_review_threads --repo owner/name --pr 123",
                "python -m scripts.github.list_unresolved_review_threads --repo owner/name --pr 123 --path docker-compose.yml --require-one",
            ],
            see_also=["scripts/github/README.md"],
        )
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
