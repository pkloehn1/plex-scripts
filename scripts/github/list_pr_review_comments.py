#!/usr/bin/env python3
"""List PR review comments with their IDs/node IDs.

Use case:
- Quickly map file/line comments to the numeric `comment_id` needed for
    reply-and-resolve automation.

This script is read-only.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from scripts.github.cli_utils import build_repo_pr_parser, resolve_repo_pr
from scripts.github.gh_cli import (
    GhRunner,
    parse_repo,
    run_actionable_main,
    run_json,
)


def list_review_comments(*, runner: GhRunner, repo: str, pr_number: int) -> list[dict[str, Any]]:
    owner, name = parse_repo(repo)
    data = run_json(
        runner,
        [
            "gh",
            "api",
            "--paginate",
            f"/repos/{owner}/{name}/pulls/{pr_number}/comments",
        ],
    )
    if not isinstance(data, list):
        raise ValueError("Unexpected comments payload")

    out: list[dict[str, Any]] = []
    for comment in data:
        if not isinstance(comment, dict):
            continue
        out.append(
            {
                "id": comment.get("id"),
                "node_id": comment.get("node_id"),
                "path": comment.get("path"),
                "line": comment.get("line"),
                "author": (comment.get("user") or {}).get("login") if isinstance(comment.get("user"), dict) else None,
                "url": comment.get("html_url"),
                "body": comment.get("body"),
            }
        )

    return out


def _build_parser() -> argparse.ArgumentParser:
    return build_repo_pr_parser("List PR review comments.")


def _run(args: argparse.Namespace, _parser: argparse.ArgumentParser, runner: GhRunner) -> int:
    resolved = resolve_repo_pr(args, runner)
    comments = list_review_comments(runner=runner, repo=resolved.repo, pr_number=resolved.pr_number)
    print(
        json.dumps(
            {"repo": resolved.repo, "pr": resolved.pr_number, "comments": comments, "count": len(comments)},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    return run_actionable_main(
        build_parser=_build_parser,
        handler=_run,
        examples=["python -m scripts.github.list_pr_review_comments --repo owner/name --pr 123"],
        see_also=["scripts/github/README.md"],
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
