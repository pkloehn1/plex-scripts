#!/usr/bin/env python3
"""List GitHub issues (excludes pull requests) with stable JSON output."""

from __future__ import annotations

import argparse
import json
from typing import Any

from scripts.github.gh_cli import (
    ActionableArgumentParser,
    GhRunner,
    current_repo,
    parse_repo,
    run_actionable_main,
    run_json,
)


def _extract_label_names(issue: dict[str, Any]) -> list[str]:
    labels = issue.get("labels")
    if not isinstance(labels, list):
        return []

    names: list[str] = []
    for label in labels:
        if not isinstance(label, dict):
            continue
        name = label.get("name")
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return names


def _extract_assignee_logins(issue: dict[str, Any]) -> list[str]:
    assignees = issue.get("assignees")
    if not isinstance(assignees, list):
        return []

    logins: list[str] = []
    for user in assignees:
        if not isinstance(user, dict):
            continue
        login = user.get("login")
        if isinstance(login, str) and login.strip():
            logins.append(login.strip())
    return logins


def list_issues(*, runner: GhRunner, repo: str, state: str = "open") -> list[dict[str, Any]]:
    owner, name = parse_repo(repo)

    payload = run_json(
        runner,
        [
            "gh",
            "api",
            "--method",
            "GET",
            "--paginate",
            f"/repos/{owner}/{name}/issues",
            "-f",
            f"state={state}",
            "-f",
            "per_page=100",
        ],
    )

    if not isinstance(payload, list):
        raise ValueError("Unexpected issues payload (expected list)")

    issues: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        if "pull_request" in item:
            continue

        number = item.get("number")
        title = item.get("title")
        if not isinstance(number, int) or not isinstance(title, str):
            continue

        issues.append(
            {
                "number": number,
                "title": title,
                "state": item.get("state"),
                "url": item.get("html_url"),
                "labels": _extract_label_names(item),
                "assignees": _extract_assignee_logins(item),
                "body": item.get("body") if isinstance(item.get("body"), str) else "",
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
            }
        )

    issues.sort(key=lambda issue: issue["number"])
    return issues


def _build_parser() -> argparse.ArgumentParser:
    parser = ActionableArgumentParser(description="List issues (excluding PRs)")
    parser.add_argument("--repo", default=None, help="Repo owner/name (default: auto-detect)")
    parser.add_argument(
        "--state",
        default="open",
        choices=["open", "closed", "all"],
        help="Issue state filter",
    )
    return parser


def _run(args: argparse.Namespace, _parser: argparse.ArgumentParser, runner: GhRunner) -> int:
    repo = args.repo or current_repo(runner)
    issues = list_issues(runner=runner, repo=repo, state=args.state)
    print(
        json.dumps(
            {"repo": repo, "state": args.state, "count": len(issues), "issues": issues},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    return run_actionable_main(
        build_parser=_build_parser,
        handler=_run,
        examples=["python -m scripts.github.list_issues --repo owner/name --state open"],
        see_also=["scripts/github/README.md"],
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
