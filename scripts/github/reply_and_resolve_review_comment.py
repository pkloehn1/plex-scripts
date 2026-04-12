#!/usr/bin/env python3
"""Reply to a PR review comment and (optionally) resolve its thread.

This script is designed for AI-agent use:
- Given a PR review comment ID (the numeric ID shown by REST endpoints), it:
    1) Posts a reply comment (`in_reply_to`)
    2) Resolves the associated review thread via GraphQL (optional)

It intentionally avoids shell quoting pitfalls by passing argv lists to
subprocess and keeping request payloads small.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.github.cli_utils import read_required_text, resolve_repo
from scripts.github.gh_cli import (
    GhCliError,
    GhRunner,
    SubprocessGhRunner,
    current_login,
    parse_repo,
    print_actionable_cli_error,
    run_json,
)


@dataclass(frozen=True)
class CommentContext:
    repo: str
    pr_number: int


@dataclass(frozen=True)
class ResultArgs:
    comment_id: int
    thread_id: str | None


_PR_NUMBER_RE = re.compile(r"/pulls/(?P<number>\d+)$")


_UNEXPECTED_GRAPHQL_RESPONSE = "Unexpected GraphQL response"


def _read_body(*, body: str | None, body_file: Path | None) -> str:
    return read_required_text(text=body, path=body_file)


def _pr_number_from_url(pull_request_url: str) -> int:
    match = _PR_NUMBER_RE.search(pull_request_url)
    if not match:
        raise ValueError("Unable to parse PR number from pull_request_url")
    return int(match.group("number"))


def fetch_comment_context(*, runner: GhRunner, repo: str, comment_id: int) -> CommentContext:
    owner, name = parse_repo(repo)

    comment = run_json(
        runner,
        [
            "gh",
            "api",
            f"/repos/{owner}/{name}/pulls/comments/{comment_id}",
        ],
    )
    if not isinstance(comment, dict):
        raise ValueError("Unexpected comment payload")

    node_id = comment.get("node_id")
    pull_request_url = comment.get("pull_request_url")
    if not isinstance(node_id, str) or not node_id.strip():
        raise ValueError("Comment missing node_id")
    if not isinstance(pull_request_url, str) or not pull_request_url.strip():
        raise ValueError("Comment missing pull_request_url")

    pr_number = _pr_number_from_url(pull_request_url)

    return CommentContext(repo=repo, pr_number=pr_number)


def post_reply(
    *,
    runner: GhRunner,
    repo: str,
    pr_number: int,
    comment_id: int,
    body: str,
) -> dict[str, Any]:
    owner, name = parse_repo(repo)
    payload = run_json(
        runner,
        [
            "gh",
            "api",
            "--method",
            "POST",
            f"/repos/{owner}/{name}/pulls/{pr_number}/comments",
            "-F",
            f"in_reply_to={comment_id}",
            "-f",
            f"body={body}",
        ],
    )
    if not isinstance(payload, dict):
        raise ValueError("Unexpected reply payload")
    return payload


def _normalize_body(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def find_existing_reply(
    *,
    runner: GhRunner,
    repo: str,
    pr_number: int,
    comment_id: int,
    body: str,
    author: str,
) -> dict[str, Any] | None:
    """Return an existing reply comment payload if it already exists.

    This provides idempotency when automation accidentally runs the script twice.
    """
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

    target_body = _normalize_body(body)

    for comment in comments:
        if not isinstance(comment, dict):
            continue

        in_reply_to = comment.get("in_reply_to")
        if in_reply_to != comment_id:
            continue

        user = comment.get("user")
        login = user.get("login") if isinstance(user, dict) else None
        if not isinstance(login, str) or login.strip() != author:
            continue

        existing_body = comment.get("body")
        if not isinstance(existing_body, str):
            continue

        if _normalize_body(existing_body) == target_body:
            return comment

    return None


def post_reply_idempotent(
    *,
    runner: GhRunner,
    repo: str,
    pr_number: int,
    comment_id: int,
    body: str,
) -> tuple[dict[str, Any], bool]:
    """Post a reply unless an identical reply already exists.

    Returns: (reply_payload, skipped)
    """
    author = current_login(runner)
    existing = find_existing_reply(
        runner=runner,
        repo=repo,
        pr_number=pr_number,
        comment_id=comment_id,
        body=body,
        author=author,
    )
    if existing is not None:
        return existing, True

    return (
        post_reply(
            runner=runner,
            repo=repo,
            pr_number=pr_number,
            comment_id=comment_id,
            body=body,
        ),
        False,
    )


_THREAD_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $after: String) {
    repository(owner: $owner, name: $name) {
        pullRequest(number: $number) {
            reviewThreads(first: 100, after: $after) {
                nodes {
                    id
                    isResolved
                    comments(first: 50) {
                        nodes { databaseId }
                    }
                }
                pageInfo { hasNextPage endCursor }
            }
        }
    }
}
""".strip()


_RESOLVE_MUTATION = """
mutation($threadId: ID!) {
    resolveReviewThread(input: { threadId: $threadId }) {
        thread { id isResolved }
    }
}
""".strip()


def _end_cursor_if_has_next(page_info: Any) -> str | None:
    if not isinstance(page_info, dict):
        return None
    if page_info.get("hasNextPage") is not True:
        return None
    cursor = page_info.get("endCursor")
    if isinstance(cursor, str) and cursor.strip():
        return cursor.strip()
    return None


def _extract_review_threads_root(query_result: Any) -> dict[str, Any]:
    if not isinstance(query_result, dict):
        raise ValueError(_UNEXPECTED_GRAPHQL_RESPONSE)
    data = query_result.get("data")
    if not isinstance(data, dict):
        raise ValueError(_UNEXPECTED_GRAPHQL_RESPONSE)
    repository = data.get("repository")
    if not isinstance(repository, dict):
        raise ValueError(_UNEXPECTED_GRAPHQL_RESPONSE)
    pull_request = repository.get("pullRequest")
    if not isinstance(pull_request, dict):
        raise ValueError(_UNEXPECTED_GRAPHQL_RESPONSE)
    threads = pull_request.get("reviewThreads")
    if not isinstance(threads, dict):
        raise ValueError(_UNEXPECTED_GRAPHQL_RESPONSE)
    return threads


def _find_thread_for_comment(*, thread_nodes: Any, comment_id: int) -> tuple[str, bool] | None:
    if not isinstance(thread_nodes, list):
        return None

    for node in thread_nodes:
        if not isinstance(node, dict):
            continue
        thread_id = node.get("id")
        if not isinstance(thread_id, str) or not thread_id.strip():
            continue

        comments = node.get("comments")
        comment_nodes = comments.get("nodes") if isinstance(comments, dict) else None
        if not isinstance(comment_nodes, list):
            continue

        if any(
            (comment_node.get("databaseId") == comment_id)
            for comment_node in comment_nodes
            if isinstance(comment_node, dict)
        ):
            return thread_id.strip(), bool(node.get("isResolved"))

    return None


def _fetch_review_threads_page(*, runner: GhRunner, repo: str, pr_number: int, after: str | None) -> dict[str, Any]:
    owner, name = parse_repo(repo)
    argv: list[str] = [
        "gh",
        "api",
        "graphql",
        "-f",
        f"query={_THREAD_QUERY}",
        "-f",
        f"owner={owner}",
        "-f",
        f"name={name}",
        "-F",
        f"number={pr_number}",
    ]
    if after:
        argv.extend(["-f", f"after={after}"])
    result = run_json(runner, argv)
    threads = _extract_review_threads_root(result)
    return threads


def _extract_thread_id_for_comment(*, runner: GhRunner, repo: str, pr_number: int, comment_id: int) -> tuple[str, bool]:
    after: str | None = None
    while True:
        threads = _fetch_review_threads_page(
            runner=runner,
            repo=repo,
            pr_number=pr_number,
            after=after,
        )

        found = _find_thread_for_comment(
            thread_nodes=threads.get("nodes"),
            comment_id=comment_id,
        )
        if found is not None:
            return found

        after = _end_cursor_if_has_next(threads.get("pageInfo"))
        if not after:
            break

    raise ValueError("Unable to locate review thread id for comment")


def resolve_review_thread(*, runner: GhRunner, repo: str, pr_number: int, comment_id: int) -> bool:
    thread_id, is_resolved = _extract_thread_id_for_comment(
        runner=runner,
        repo=repo,
        pr_number=pr_number,
        comment_id=comment_id,
    )
    if is_resolved:
        return True
    return resolve_review_thread_id(runner=runner, thread_id=thread_id)


def resolve_review_thread_id(*, runner: GhRunner, thread_id: str) -> bool:
    if not thread_id.strip():
        raise ValueError("thread_id is required")

    mutation_result = run_json(
        runner,
        [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={_RESOLVE_MUTATION}",
            "-f",
            f"threadId={thread_id}",
        ],
    )
    if not isinstance(mutation_result, dict):
        raise ValueError("Unexpected GraphQL mutation response")

    resolved = (mutation_result.get("data") or {}).get("resolveReviewThread", {}).get("thread", {}).get("isResolved")
    return bool(resolved)


def _build_parser() -> argparse.ArgumentParser:
    from scripts.github.gh_cli import ActionableArgumentParser

    parser = ActionableArgumentParser(description="Reply to a PR review comment and resolve its thread.")
    parser.add_argument("--repo", default=None, help="Repo owner/name (default: auto-detect)")
    parser.add_argument("--comment-id", required=True, type=int, help="Review comment ID")
    parser.add_argument(
        "--pr",
        type=int,
        default=None,
        help=(
            "PR number. If provided, avoids the extra REST lookup for the PR number. "
            "If omitted, the script queries the review comment via REST to derive the PR."
        ),
    )
    parser.add_argument(
        "--thread-id",
        help=(
            "Review thread ID (GraphQL id). If provided, thread resolution uses this id "
            "directly instead of attempting to derive it from the comment."
        ),
    )
    parser.add_argument(
        "--resolve-only",
        action="store_true",
        help=(
            "Resolve the review thread without posting a reply. Use this when a reply "
            "was already posted and only resolution is needed."
        ),
    )
    parser.add_argument("--body", help="Reply body")
    parser.add_argument("--body-file", type=Path, help="Path to file containing reply body")
    parser.add_argument(
        "--no-resolve",
        action="store_true",
        help="Post reply but do not resolve the review thread",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON result to stdout (default: text)",
    )
    return parser


def _resolve_body(args: argparse.Namespace) -> str | None:
    if args.resolve_only:
        return None
    return _read_body(body=args.body, body_file=args.body_file)


def _resolve_comment_context(*, runner: GhRunner, args: argparse.Namespace) -> CommentContext:
    repo = resolve_repo(args, runner)
    if args.pr is not None:
        return CommentContext(repo=repo, pr_number=int(args.pr))
    return fetch_comment_context(runner=runner, repo=repo, comment_id=int(args.comment_id))


def _maybe_post_reply(
    *,
    runner: GhRunner,
    ctx: CommentContext,
    comment_id: int,
    body: str | None,
) -> dict[str, Any] | None:
    if body is None:
        return None
    reply, _already_existed = post_reply_idempotent(
        runner=runner,
        repo=ctx.repo,
        pr_number=ctx.pr_number,
        comment_id=comment_id,
        body=body,
    )
    return reply


def _post_reply_if_needed(
    *,
    runner: GhRunner,
    ctx: CommentContext,
    comment_id: int,
    body: str | None,
) -> tuple[dict[str, Any] | None, bool | None]:
    if body is None:
        return None, None
    return post_reply_idempotent(
        runner=runner,
        repo=ctx.repo,
        pr_number=ctx.pr_number,
        comment_id=comment_id,
        body=body,
    )


def _maybe_resolve_thread(
    *,
    runner: GhRunner,
    ctx: CommentContext,
    comment_id: int,
    no_resolve: bool,
    thread_id: str | None,
) -> bool | None:
    if no_resolve:
        return None
    if thread_id:
        return resolve_review_thread_id(runner=runner, thread_id=thread_id)
    return resolve_review_thread(
        runner=runner,
        repo=ctx.repo,
        pr_number=ctx.pr_number,
        comment_id=comment_id,
    )


def _build_result(
    *,
    ctx: CommentContext,
    args: ResultArgs,
    reply: dict[str, Any] | None,
    reply_skipped: bool | None,
    resolved: bool | None,
) -> dict[str, Any]:
    return {
        "repo": ctx.repo,
        "pr": ctx.pr_number,
        "in_reply_to": args.comment_id,
        "thread_id": args.thread_id,
        "reply_id": reply.get("id") if isinstance(reply, dict) else None,
        "reply_node_id": reply.get("node_id") if isinstance(reply, dict) else None,
        "reply_skipped": reply_skipped,
        "resolved": resolved,
    }


def _run(args: argparse.Namespace, *, runner: GhRunner) -> dict[str, Any]:
    comment_id = int(args.comment_id)
    body = _resolve_body(args)
    ctx = _resolve_comment_context(runner=runner, args=args)
    reply, reply_skipped = _post_reply_if_needed(
        runner=runner,
        ctx=ctx,
        comment_id=comment_id,
        body=body,
    )
    resolved = _maybe_resolve_thread(
        runner=runner,
        ctx=ctx,
        comment_id=comment_id,
        no_resolve=bool(args.no_resolve),
        thread_id=args.thread_id,
    )
    return _build_result(
        ctx=ctx,
        args=ResultArgs(comment_id=comment_id, thread_id=args.thread_id),
        reply=reply,
        reply_skipped=reply_skipped,
        resolved=resolved,
    )


def _emit_result(*, args: argparse.Namespace, result: dict[str, Any]) -> None:
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    pr_number = result["pr"]
    print(f"Replied to comment {args.comment_id} on PR #{pr_number}.")
    resolved = result["resolved"]
    if resolved is True:
        print("Resolved review thread.")
    elif resolved is False:
        print("Review thread not resolved (API returned false).")


def main() -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args()
        runner = SubprocessGhRunner()
        result = _run(args, runner=runner)
        _emit_result(args=args, result=result)
        return 0
    except (GhCliError, ValueError) as exc:
        error_result = {
            "status": "error",
            "message": str(exc),
            "error": str(exc),
        }
        if "args" in locals() and getattr(args, "json", False):  # type: ignore[name-defined]
            print(json.dumps(error_result, indent=2, sort_keys=True))
            return 2

        print_actionable_cli_error(
            exc,
            parser=parser,
            examples=[
                "python -m scripts.github.reply_and_resolve_review_comment --repo owner/name --comment-id 123 --pr 104",
                "python -m scripts.github.reply_and_resolve_review_comment --repo owner/name --comment-id 123 --resolve-only",
            ],
            see_also=["scripts/github/README.md"],
        )
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
