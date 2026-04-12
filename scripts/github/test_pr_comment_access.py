#!/usr/bin/env python3
"""Test access from this device to respond to PR comment threads.

This script performs a series of read-only and write tests to verify:
1. Authentication status
2. Ability to list PR review comments
3. Ability to fetch comment context
4. Ability to post replies (optional, controlled by --test-write flag)
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from scripts.common.encoding import ensure_utf8_stdio
from scripts.github.gh_cli import (
    GhRunner,
    SubprocessGhRunner,
    current_repo,
    print_actionable_cli_error,
    run_json,
)
from scripts.github.list_pr_review_comments import list_review_comments
from scripts.github.reply_and_resolve_review_comment import (
    fetch_comment_context,
    post_reply_idempotent,
)

ensure_utf8_stdio()


def verify_authentication(runner: GhRunner) -> dict[str, str]:
    """Verify GitHub CLI authentication."""
    print("Testing authentication...")
    try:
        user_data = run_json(runner, ["gh", "api", "/user"])
        login = user_data.get("login", "unknown")
        print(f"[OK] Authenticated as: {login}")
        return {"status": "success", "login": login}
    except Exception as error:
        print(f"[FAIL] Authentication failed: {error}")
        return {"status": "failed", "error": str(error)}


def verify_list_comments(runner: GhRunner, repo: str, pr_number: int) -> dict[str, Any]:
    """Verify listing PR review comments."""
    print(f"\nTesting list PR review comments (PR #{pr_number})...")
    try:
        comments = list_review_comments(runner=runner, repo=repo, pr_number=pr_number)
        count = len(comments)
        print(f"[OK] Found {count} review comment(s)")
        if count > 0:
            sample_ids = [comment.get("id") for comment in comments[:3]]
            print(f"  Sample comment IDs: {sample_ids}")
        return {"status": "success", "count": count, "comments": comments}
    except Exception as error:
        print(f"[FAIL] Failed to list comments: {error}")
        return {"status": "failed", "error": str(error)}


def verify_fetch_comment_context(runner: GhRunner, repo: str, comment_id: int) -> dict[str, Any]:
    """Verify fetching comment context."""
    print(f"\nTesting fetch comment context (comment ID: {comment_id})...")
    try:
        ctx = fetch_comment_context(runner=runner, repo=repo, comment_id=comment_id)
        print(f"[OK] Fetched context: PR #{ctx.pr_number}, repo: {ctx.repo}")
        return {
            "status": "success",
            "pr_number": ctx.pr_number,
            "repo": ctx.repo,
        }
    except Exception as error:
        print(f"[FAIL] Failed to fetch comment context: {error}")
        return {"status": "failed", "error": str(error)}


def verify_post_reply(
    runner: GhRunner,
    repo: str,
    pr_number: int,
    comment_id: int,
    test_body: str,
) -> dict[str, Any]:
    """Verify posting a reply to a PR review comment."""
    print(f"\nTesting post reply to comment {comment_id}...")
    try:
        # Post the reply
        reply, skipped = post_reply_idempotent(
            runner=runner,
            repo=repo,
            pr_number=pr_number,
            comment_id=comment_id,
            body=test_body,
        )

        if skipped:
            print("[OK] Reply skipped (duplicate detected)")
        else:
            reply_id = reply.get("id")
            print(f"[OK] Posted reply (ID: {reply_id})")

        return {
            "status": "success",
            "skipped": skipped,
            "reply_id": reply.get("id"),
            "reply_node_id": reply.get("node_id"),
        }
    except Exception as error:
        print(f"[FAIL] Failed to post reply: {error}")
        return {"status": "failed", "error": str(error)}


def main() -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args()
    except ValueError as exc:
        print_actionable_cli_error(
            exc,
            parser=parser,
            examples=[
                "python -m scripts.github.test_pr_comment_access --repo owner/name --pr 104",
                "python -m scripts.github.test_pr_comment_access --repo owner/name --pr 104 --comment-id 123 --test-write",
            ],
            see_also=["scripts/github/README.md"],
        )
        return 2

    runner = SubprocessGhRunner()

    repo = _determine_repo(args, runner)
    if not repo:
        return 1

    results = {"repo": repo, "pr": args.pr, "tests": {}}

    if _run_tests(args, runner, repo, results) != 0:
        _maybe_print_json(args.json, results)
        return 1

    _print_summary(args.json, results)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    from scripts.github.gh_cli import ActionableArgumentParser

    parser = ActionableArgumentParser(description="Test access to PR comment threads from this device")
    parser.add_argument("--repo", help="GitHub repo (owner/name). Defaults to current repo.")
    parser.add_argument(
        "--pr",
        type=int,
        required=True,
        help="PR number to test with",
    )
    parser.add_argument(
        "--comment-id",
        type=int,
        help="Specific comment ID to test with. If not provided, uses the first comment found.",
    )
    parser.add_argument(
        "--test-write",
        action="store_true",
        help="Test write operations (post a reply). Default is read-only.",
    )
    parser.add_argument(
        "--test-body",
        default="Test reply from device access verification script.",
        help="Body text for test reply (only used with --test-write)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    return parser


def _determine_repo(args: argparse.Namespace, runner: GhRunner) -> str | None:
    if args.repo:
        repo_str: str = args.repo
        return repo_str
    try:
        repo = current_repo(runner)
        print(f"Using current repo: {repo}")
        return repo
    except Exception as error:
        print(f"Error determining repo: {error}")
        return None


def _run_tests(
    args: argparse.Namespace,
    runner: GhRunner,
    repo: str,
    results: dict[str, Any],
) -> int:
    auth_result = verify_authentication(runner)
    results["tests"]["authentication"] = auth_result
    if auth_result["status"] != "success":
        print("\n[FAIL] Authentication failed. Cannot proceed.")
        return 1

    list_result = verify_list_comments(runner, repo, args.pr)
    results["tests"]["list_comments"] = list_result
    if list_result["status"] != "success":
        print("\n[FAIL] Failed to list comments. Cannot proceed.")
        return 1

    comment_id = _select_comment_id(args.comment_id, list_result, results)
    if comment_id is None:
        return 1

    context_result = verify_fetch_comment_context(runner, repo, comment_id)
    results["tests"]["fetch_context"] = context_result
    if context_result["status"] != "success":
        print("\n[FAIL] Failed to fetch comment context.")
        return 1

    if not _handle_reply_test(args, runner, repo, comment_id, results):
        return 1
    return 0


def _select_comment_id(cli_comment_id: int | None, list_result: dict[str, Any], results: dict[str, Any]) -> int | None:
    if cli_comment_id:
        results["comment_id"] = cli_comment_id
        return cli_comment_id

    comments = list_result.get("comments", [])
    if not comments:
        print("\n[FAIL] No comments found in PR. Cannot test comment operations.")
        return None

    raw_id = comments[0].get("id")
    print(f"\nUsing first comment ID: {raw_id}")
    results["comment_id"] = raw_id
    comment_id: int | None = raw_id
    return comment_id


def _handle_reply_test(
    args: argparse.Namespace,
    runner: GhRunner,
    repo: str,
    comment_id: int,
    results: dict[str, Any],
) -> bool:
    if not args.test_write:
        results["tests"]["post_reply"] = {
            "status": "skipped",
            "message": "Use --test-write to test write operations",
        }
        print("\n[INFO] Write test skipped (use --test-write to enable)")
        return True

    reply_result = verify_post_reply(
        runner,
        repo,
        args.pr,
        comment_id,
        args.test_body,
    )
    results["tests"]["post_reply"] = reply_result
    if reply_result["status"] != "success":
        print("\n[FAIL] Failed to post reply.")
        return False
    return True


def _print_summary(json_output: bool, results: dict[str, Any]) -> None:
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    all_passed = all(test.get("status") in ("success", "skipped") for test in results["tests"].values())
    print("[OK] All tests passed!" if all_passed else "[FAIL] Some tests failed")
    _maybe_print_json(json_output, results)


def _maybe_print_json(json_output: bool, results: dict[str, Any]) -> None:
    if json_output:
        print(json.dumps(results, indent=2))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
