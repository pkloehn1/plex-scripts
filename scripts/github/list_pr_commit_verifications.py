#!/usr/bin/env python3
"""List PR commits and their GitHub signature verification status.

Use case:
- Quickly diagnose why GitHub shows commits as unsigned / unverified.
- Provide stable JSON output without jq pipelines.

Notes on verification reasons (as returned by the GitHub API):
- valid: signature verified
- unsigned: commit has no signature
- no_user: signature present, but the signing identity is not associated with a GitHub user

This script is read-only.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from typing import Any

from scripts.github.gh_cli import (
    ActionableArgumentParser,
    GhCliError,
    GhRunner,
    SubprocessGhRunner,
    active_pr_number,
    current_repo,
    parse_repo,
    print_actionable_cli_error,
    run_json,
)


def list_pr_commit_verifications(*, runner: GhRunner, repo: str, pr: int) -> list[dict[str, Any]]:
    owner, name = parse_repo(repo)
    data = run_json(
        runner,
        [
            "gh",
            "api",
            "--paginate",
            f"/repos/{owner}/{name}/pulls/{pr}/commits",
        ],
    )
    if not isinstance(data, list):
        raise ValueError("Unexpected commits payload")

    out: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue

        commit_obj = item.get("commit")
        commit: dict[str, Any] = commit_obj if isinstance(commit_obj, dict) else {}

        verification_obj = commit.get("verification")
        verification: dict[str, Any] = verification_obj if isinstance(verification_obj, dict) else {}

        message_obj = commit.get("message")
        message = message_obj if isinstance(message_obj, str) else ""
        subject = message.splitlines()[0] if message else ""

        out.append(
            {
                "sha": item.get("sha"),
                "html_url": item.get("html_url"),
                "subject": subject,
                "verified": verification.get("verified"),
                "reason": verification.get("reason"),
                "signature": verification.get("signature"),
                "payload": verification.get("payload"),
                "verified_at": verification.get("verified_at"),
                "author": commit.get("author"),
                "committer": commit.get("committer"),
            }
        )

    return out


def summarize_reasons(commits: list[dict[str, Any]]) -> dict[str, int]:
    reasons: list[str] = []
    for commit_entry in commits:
        reason = commit_entry.get("reason")
        if isinstance(reason, str) and reason:
            reasons.append(reason)
        else:
            reasons.append("unknown")

    counts = Counter(reasons)
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def filter_commits(commits: list[dict[str, Any]], *, only_failing: bool) -> list[dict[str, Any]]:
    if not only_failing:
        return commits

    out: list[dict[str, Any]] = []
    for commit_entry in commits:
        verified = commit_entry.get("verified")
        if verified is True:
            continue
        out.append(commit_entry)
    return out


def _parse_fail_reasons(value: str | None) -> set[str]:
    if not value:
        return set()
    return {item.strip() for item in value.split(",") if item.strip()}


def _should_fail(commits: list[dict[str, Any]], fail_reasons: set[str]) -> bool:
    if not fail_reasons:
        return False
    for commit_entry in commits:
        reason = commit_entry.get("reason")
        if isinstance(reason, str) and reason in fail_reasons:
            return True
    return False


def _build_parser() -> argparse.ArgumentParser:
    parser = ActionableArgumentParser(description="List PR commits and signature verification status.")
    parser.add_argument("--repo", default=None, help="Repo owner/name (default: auto-detect)")
    parser.add_argument("--pr", type=int, default=None, help="PR number (default: active PR)")
    parser.add_argument(
        "--only-failing",
        action="store_true",
        help="Only include commits where GitHub verification is not true",
    )
    parser.add_argument(
        "--fail-on",
        default=None,
        help=(
            "Comma-separated list of verification reasons that should cause a non-zero exit. Example: unsigned,no_user"
        ),
    )
    return parser


def _parse_args() -> argparse.Namespace:
    return _build_parser().parse_args()


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    runner = SubprocessGhRunner()

    try:
        repo = args.repo or current_repo(runner)
        pr = args.pr or active_pr_number(runner)

        commits = list_pr_commit_verifications(runner=runner, repo=repo, pr=pr)
        reasons = summarize_reasons(commits)

        filtered = filter_commits(commits, only_failing=args.only_failing)

        payload = {
            "repo": repo,
            "pr": pr,
            "count": len(commits),
            "reasons": reasons,
            "commits": filtered,
        }

        print(json.dumps(payload, indent=2, sort_keys=True))

        fail_reasons = _parse_fail_reasons(args.fail_on)
        if _should_fail(commits, fail_reasons):
            return 2

        return 0
    except (GhCliError, ValueError) as err:
        print_actionable_cli_error(
            err,
            parser=parser,
            examples=[
                "python -m scripts.github.list_pr_commit_verifications --repo owner/name --pr 123",
                "python -m scripts.github.list_pr_commit_verifications --repo owner/name --pr 123 --only-failing",
            ],
            see_also=["scripts/github/README.md"],
        )
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
