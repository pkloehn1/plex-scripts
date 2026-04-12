#!/usr/bin/env python3
"""Diff required status contexts vs reported statuses on a PR head SHA.

Use case:
- Identify missing required status contexts caused by naming mismatches
    (workflow/job name changes, punctuation differences, etc.).

This script is read-only.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from dataclasses import dataclass
from typing import Any

from scripts.github.cli_utils import build_repo_pr_parser, resolve_repo_pr
from scripts.github.gh_cli import (
    GhRunner,
    parse_repo,
    run_actionable_main,
    run_json,
)
from scripts.github.rulesets import (
    fetch_ruleset,
    list_rulesets,
    required_status_check_contexts,
)


@dataclass(frozen=True)
class ContextDiff:
    required: list[str]
    present: list[str]
    missing: list[str]
    extra: list[str]


def _head_sha(*, runner: GhRunner, repo: str, pr_number: int) -> str:
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
            "commits",
        ],
    )
    commits = data.get("commits") if isinstance(data, dict) else None
    if not isinstance(commits, list) or not commits:
        raise ValueError("Unable to read PR commits")
    last = commits[-1]
    oid = last.get("oid") if isinstance(last, dict) else None
    if not isinstance(oid, str) or not oid.strip():
        raise ValueError("Unable to determine head SHA")
    return oid.strip()


def _required_contexts_union(*, runner: GhRunner, repo: str) -> set[str]:
    contexts: set[str] = set()
    for ruleset in list_rulesets(runner=runner, repo=repo):
        rid = ruleset.get("id")
        if not isinstance(rid, int):
            continue
        full = fetch_ruleset(runner=runner, repo=repo, ruleset_id=rid)
        contexts |= required_status_check_contexts(full)
    return contexts


def _present_status_contexts(*, runner: GhRunner, repo: str, sha: str) -> set[str]:
    owner, name = parse_repo(repo)
    payload = run_json(
        runner,
        [
            "gh",
            "api",
            f"/repos/{owner}/{name}/commits/{sha}/status",
        ],
    )
    statuses = payload.get("statuses") if isinstance(payload, dict) else None
    if not isinstance(statuses, list):
        return set()

    out: set[str] = set()
    for status in statuses:
        if not isinstance(status, dict):
            continue
        ctx = status.get("context")
        if isinstance(ctx, str) and ctx.strip():
            out.add(ctx.strip())
    return out


def diff_required_contexts(*, runner: GhRunner, repo: str, pr_number: int) -> dict[str, Any]:
    sha = _head_sha(runner=runner, repo=repo, pr_number=pr_number)

    required = _required_contexts_union(runner=runner, repo=repo)
    present = _present_status_contexts(runner=runner, repo=repo, sha=sha)

    missing = sorted(required - present)
    extra = sorted(present - required)

    return {
        "repo": repo,
        "pr": pr_number,
        "head_sha": sha,
        "diff": dataclasses.asdict(
            ContextDiff(
                required=sorted(required),
                present=sorted(present),
                missing=missing,
                extra=extra,
            )
        ),
    }


def _build_parser() -> argparse.ArgumentParser:
    return build_repo_pr_parser("Diff required status contexts vs check runs.")


def _run(args: argparse.Namespace, _parser: argparse.ArgumentParser, runner: GhRunner) -> int:
    resolved = resolve_repo_pr(args, runner)
    print(
        json.dumps(
            diff_required_contexts(runner=runner, repo=resolved.repo, pr_number=resolved.pr_number),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    return run_actionable_main(
        build_parser=_build_parser,
        handler=_run,
        examples=["python -m scripts.github.diff_required_status_contexts --repo owner/name --pr 123"],
        see_also=["scripts/github/README.md"],
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
