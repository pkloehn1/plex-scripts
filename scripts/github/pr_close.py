#!/usr/bin/env python3
"""Close a GitHub pull request.

Why this exists:
- Repo policy is to interact with GitHub via `scripts/github/*` helpers rather than
    calling `gh` directly.
- Occasionally automation creates stray PRs; this provides a safe, testable way
    to close them.
"""

from __future__ import annotations

import argparse
import json

from scripts.github.cli_utils import resolve_repo
from scripts.github.gh_cli import (
    ActionableArgumentParser,
    GhRunner,
    parse_repo,
    run_actionable_main,
    run_text,
)


def close_pr(
    *,
    runner: GhRunner,
    repo: str,
    pr_number: int,
    delete_branch: bool = False,
    comment: str | None = None,
) -> dict[str, object]:
    if pr_number <= 0:
        raise ValueError("pr_number must be positive")

    parse_repo(repo)  # validates owner/name format

    if comment is not None and comment.strip():
        run_text(
            runner,
            [
                "gh",
                "pr",
                "comment",
                str(pr_number),
                "--repo",
                repo,
                "--body",
                comment,
            ],
        )

    argv: list[str] = ["gh", "pr", "close", str(pr_number), "--repo", repo]
    if delete_branch:
        argv.append("--delete-branch")

    run_text(runner, argv)

    return {
        "ok": True,
        "repo": repo,
        "pr": pr_number,
        "delete_branch": delete_branch,
        "commented": bool(comment and comment.strip()),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = ActionableArgumentParser(description="Close a GitHub pull request.")
    parser.add_argument("--repo", default=None, help="Repo owner/name (default: auto-detect)")
    parser.add_argument("--pr", type=int, required=True, help="PR number")
    parser.add_argument(
        "--delete-branch",
        action="store_true",
        help="Delete the head branch after closing the PR.",
    )
    parser.add_argument(
        "--comment",
        help="Optional comment to post before closing.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    return parser


def _run(args: argparse.Namespace, _parser: argparse.ArgumentParser, runner: GhRunner) -> int:
    repo = resolve_repo(args, runner)
    payload = close_pr(
        runner=runner,
        repo=repo,
        pr_number=args.pr,
        delete_branch=bool(args.delete_branch),
        comment=args.comment,
    )

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Closed PR #{args.pr} in {repo}.")

    return 0


def main() -> int:
    return run_actionable_main(
        build_parser=_build_parser,
        handler=_run,
        examples=[
            "python -m scripts.github.pr_close --repo owner/name --pr 123",
            "python -m scripts.github.pr_close --repo owner/name --pr 123 --delete-branch",
        ],
        see_also=["scripts/github/README.md"],
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
