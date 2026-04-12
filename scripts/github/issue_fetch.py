#!/usr/bin/env python3
"""Fetch a single GitHub issue and return structured details.

Why this exists:
- Repo policy requires GitHub interaction via ``scripts/github/*`` helpers.
- Provides a testable, CLI-accessible way to retrieve issue metadata
    (title, body, state, labels, assignees, milestone) as structured JSON.
- Exposes ``fetch_issue()`` as the shared function for any script that
    needs single-issue data from the GitHub REST API.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from scripts.github.cli_utils import resolve_repo
from scripts.github.gh_cli import (
    ActionableArgumentParser,
    GhRunner,
    parse_repo,
    run_actionable_main,
    run_json,
)


def fetch_issue(
    *,
    runner: GhRunner,
    repo: str,
    number: int,
) -> dict[str, Any]:
    """Fetch a single GitHub issue via the REST API.

    Returns the raw API response dict.  This is the canonical shared
    function for retrieving single-issue data — other helpers should
    import it rather than duplicating the GET call.
    """
    if number <= 0:
        raise ValueError("number must be positive")

    owner, name = parse_repo(repo)
    payload = run_json(
        runner,
        ["gh", "api", f"/repos/{owner}/{name}/issues/{number}"],
    )
    if not isinstance(payload, dict):
        raise ValueError("Unexpected issue payload")
    return payload


def _safe_str_list(items: Any, key: str) -> list[str]:
    """Extract sorted string values from a list of dicts, tolerating nulls."""
    if not isinstance(items, list):
        return []
    return sorted(entry[key] for entry in items if isinstance(entry, dict) and isinstance(entry.get(key), str))


def _structure_issue(raw: dict[str, Any], repo: str) -> dict[str, Any]:
    """Extract key fields from the raw API response for CLI output."""
    labels = _safe_str_list(raw.get("labels"), "name")
    assignees = _safe_str_list(raw.get("assignees"), "login")
    milestone_obj = raw.get("milestone")
    title = milestone_obj.get("title") if isinstance(milestone_obj, dict) else None
    milestone = title if isinstance(title, str) else None
    return {
        "repo": repo,
        "number": raw.get("number"),
        "title": raw.get("title"),
        "body": raw.get("body"),
        "state": raw.get("state"),
        "labels": labels,
        "assignees": assignees,
        "milestone": milestone,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = ActionableArgumentParser(description="Fetch a single GitHub issue.")
    parser.add_argument("--repo", default=None, help="Repo owner/name (default: auto-detect)")
    parser.add_argument("--number", type=int, required=True, help="Issue number")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    return parser


def _run(args: argparse.Namespace, _parser: argparse.ArgumentParser, runner: GhRunner) -> int:
    repo = resolve_repo(args, runner)
    raw = fetch_issue(runner=runner, repo=repo, number=args.number)
    result = _structure_issue(raw, repo)

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Issue #{result['number']}: {result['title']} [{result['state']}]")

    return 0


def main() -> int:
    return run_actionable_main(
        build_parser=_build_parser,
        handler=_run,
        examples=[
            "python -m scripts.github.issue_fetch --repo owner/name --number 123",
            "python -m scripts.github.issue_fetch --repo owner/name --number 123 --json",
        ],
        see_also=["scripts/github/README.md"],
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
