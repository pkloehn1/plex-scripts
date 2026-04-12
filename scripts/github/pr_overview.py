#!/usr/bin/env python3
"""Summarize PR mergeability, reviews, and checks via `gh pr view`.

Use case:
- Reduce trial/error by emitting a single JSON payload containing the most
    relevant PR gate info.

This script does not attempt to interpret org rulesets; it reports what GitHub
returns for the PR (including statusCheckRollup when available).
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from scripts.github.cli_utils import build_repo_pr_parser, resolve_repo_pr
from scripts.github.gh_cli import (
    GhRunner,
    run_actionable_main,
    run_json,
)


def pr_overview(*, runner: GhRunner, repo: str, pr_number: int) -> dict[str, Any]:
    data = run_json(
        runner,
        [
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--repo",
            repo,
            "--json",
            "number,url,title,mergeable,reviewDecision,headRefName,baseRefName,commits,statusCheckRollup",
        ],
    )
    if not isinstance(data, dict):
        raise ValueError("Unexpected gh pr view payload")
    return data


def _build_parser() -> argparse.ArgumentParser:
    return build_repo_pr_parser("Summarize PR state (mergeability/checks/reviews).")


def _run(args: argparse.Namespace, _parser: argparse.ArgumentParser, runner: GhRunner) -> int:
    resolved = resolve_repo_pr(args, runner)
    payload = pr_overview(runner=runner, repo=resolved.repo, pr_number=resolved.pr_number)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def main() -> int:
    return run_actionable_main(
        build_parser=_build_parser,
        handler=_run,
        examples=["python -m scripts.github.pr_overview --repo owner/name --pr 123"],
        see_also=["scripts/github/README.md"],
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
