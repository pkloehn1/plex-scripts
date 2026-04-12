#!/usr/bin/env python3
"""Create or edit GitHub issues via `gh api`.

Goal: provide a single, predictable entrypoint for AI agents.

- Create: omit --number (POST /issues)
- Edit: provide --number (PATCH /issues/{number})

This script does not attempt to manage issue templates or project boards.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.github.cli_utils import resolve_body, resolve_repo
from scripts.github.gh_cli import (
    ActionableArgumentParser,
    GhRunner,
    parse_repo,
    run_actionable_main,
    run_json,
)
from scripts.github.issue_fetch import fetch_issue


def _extract_label_names(issue: dict[str, Any]) -> set[str]:
    labels = issue.get("labels")
    if not isinstance(labels, list):
        return set()

    out: set[str] = set()
    for label in labels:
        if not isinstance(label, dict):
            continue
        name = label.get("name")
        if isinstance(name, str) and name.strip():
            out.add(name.strip())
    return out


def _extract_assignee_logins(issue: dict[str, Any]) -> set[str]:
    assignees = issue.get("assignees")
    if not isinstance(assignees, list):
        return set()

    out: set[str] = set()
    for user in assignees:
        if not isinstance(user, dict):
            continue
        login = user.get("login")
        if isinstance(login, str) and login.strip():
            out.add(login.strip())
    return out


def _normalize_str_list(values: list[str] | None) -> set[str]:
    if not values:
        return set()
    out: set[str] = set()
    for value in values:
        if isinstance(value, str) and value.strip():
            out.add(value.strip())
    return out


def _merge_existing_fields(
    *,
    existing: dict[str, Any],
    labels: list[str] | None,
    assignees: list[str] | None,
) -> tuple[list[str], list[str]]:
    existing_labels = _extract_label_names(existing)
    existing_assignees = _extract_assignee_logins(existing)

    merged_labels = sorted(existing_labels | _normalize_str_list(labels))
    merged_assignees = sorted(existing_assignees | _normalize_str_list(assignees))
    return merged_labels, merged_assignees


def _issue_method_endpoint(*, owner: str, name: str, number: int | None, title: str | None) -> tuple[str, str]:
    if number is None:
        if not isinstance(title, str) or not title.strip():
            raise ValueError("--title is required when creating an issue")
        return "POST", f"/repos/{owner}/{name}/issues"

    if number <= 0:
        raise ValueError("--number must be a positive integer")
    return "PATCH", f"/repos/{owner}/{name}/issues/{number}"


def upsert_issue(
    *,
    runner: GhRunner,
    repo: str,
    number: int | None,
    title: str | None,
    body: str | None,
    labels: list[str] | None,
    assignees: list[str] | None,
    merge_existing: bool = False,
) -> dict[str, Any]:
    owner, name = parse_repo(repo)

    merged_labels = labels
    merged_assignees = assignees
    if merge_existing and number is not None:
        existing = fetch_issue(runner=runner, repo=repo, number=number)
        merged_labels, merged_assignees = _merge_existing_fields(
            existing=existing,
            labels=labels,
            assignees=assignees,
        )

    method, endpoint = _issue_method_endpoint(
        owner=owner,
        name=name,
        number=number,
        title=title,
    )

    argv: list[str] = ["gh", "api", "--method", method, endpoint]

    for field, value in [("title", title), ("body", body)]:
        if value is not None:
            argv.extend(["-f", f"{field}={value}"])
    for label in merged_labels or []:
        argv.extend(["-f", f"labels[]={label}"])
    for assignee in merged_assignees or []:
        argv.extend(["-f", f"assignees[]={assignee}"])

    payload = run_json(runner, argv)
    if not isinstance(payload, dict):
        raise ValueError("Unexpected issue payload")
    return payload


def _build_parser() -> argparse.ArgumentParser:
    parser = ActionableArgumentParser(description="Create or edit a GitHub issue.")
    parser.add_argument("--repo", default=None, help="Repo owner/name (default: auto-detect)")
    parser.add_argument("--number", type=int, help="Issue number (edit mode)")
    parser.add_argument("--title", help="Issue title")
    parser.add_argument("--body", help="Issue body")
    parser.add_argument("--body-file", type=Path, help="Path to issue body file")
    parser.add_argument(
        "--label",
        action="append",
        default=None,
        help="Label to add (repeatable)",
    )
    parser.add_argument(
        "--assignee",
        action="append",
        default=None,
        help="Assignee to add (repeatable)",
    )
    parser.add_argument(
        "--merge-existing",
        action="store_true",
        help=(
            "In edit mode, merge existing labels/assignees from the issue with the provided ones. "
            "Use this to add a label/assignee without re-listing the full set."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    return parser


def _run(args: argparse.Namespace, _parser: argparse.ArgumentParser, runner: GhRunner) -> int:
    repo = resolve_repo(args, runner)
    body = resolve_body(args)

    issue = upsert_issue(
        runner=runner,
        repo=repo,
        number=args.number,
        title=args.title,
        body=body,
        labels=args.label,
        assignees=args.assignee,
        merge_existing=bool(args.merge_existing),
    )

    result = {
        "repo": repo,
        "number": issue.get("number"),
        "url": issue.get("html_url"),
        "title": issue.get("title"),
        "state": issue.get("state"),
    }

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Issue #{result['number']}: {result['url']}")

    return 0


def main() -> int:
    return run_actionable_main(
        build_parser=_build_parser,
        handler=_run,
        examples=[
            'python -m scripts.github.issue_upsert --repo owner/name --title "My issue" --body "..."',
            "python -m scripts.github.issue_upsert --repo owner/name --number 123 --label status/wip --merge-existing",
        ],
        see_also=["scripts/github/README.md"],
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
