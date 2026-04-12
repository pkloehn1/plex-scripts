#!/usr/bin/env python3
"""Rewrite open issues to the Work Package template body (dry-run by default)."""

from __future__ import annotations

import argparse
import json
from typing import Any

from scripts.github.gh_cli import (
    ActionableArgumentParser,
    GhCliError,
    GhRunner,
    SubprocessGhRunner,
    current_repo,
    print_actionable_cli_error,
)
from scripts.github.issue_upsert import upsert_issue
from scripts.github.list_issues import list_issues

_WORK_PACKAGE_BODY = """## Objective
TBD

## Risk level
low | medium | high

## Affected services/paths
- TBD

## Rollback plan
- Revert commit(s)
- Roll back config change
- Validate service health

## Deliverables
- TBD

## Acceptance criteria
- [ ] Feature or workflow behaves as documented for the target use case
- [ ] Configuration or code change applies without errors in affected environments
- [ ] No regressions observed in listed affected services/paths
- [ ] Documentation and examples updated where behavior or usage has changed

## Validation plan
- [ ] Pre-commit hooks pass
- [ ] Relevant unit tests added/updated and passing
- [ ] CI green (Super-Linter, actionlint, tests if applicable)
- [ ] No secrets introduced (gitleaks clean)

## TDD Requirements
- [ ] Write failing test first (Red)
- [ ] Implement minimal code to pass test (Green)
- [ ] Refactor for quality/maintainability (Refactor)
- [ ] Test coverage >80% for new code

## Dependencies
#123, #456

## Estimate
1h | 2h | 3h"""


def _normalize_body(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def build_work_package_body() -> str:
    return _WORK_PACKAGE_BODY


def refactor_open_issues(*, runner: GhRunner, repo: str, apply: bool = False) -> dict[str, Any]:
    body = build_work_package_body()
    normalized_target = _normalize_body(body)

    issues = list_issues(runner=runner, repo=repo, state="open")

    updated_numbers: list[int] = []
    for issue in issues:
        number = issue.get("number")
        if not isinstance(number, int):
            continue

        raw_body = issue.get("body")
        existing_body: str = raw_body if isinstance(raw_body, str) else ""
        if _normalize_body(existing_body) == normalized_target:
            continue

        if apply:
            upsert_issue(
                runner=runner,
                repo=repo,
                number=number,
                title=None,
                body=body,
                labels=None,
                assignees=None,
                merge_existing=False,
            )

        updated_numbers.append(number)

    return {
        "repo": repo,
        "apply": apply,
        "total_open_issues": len(issues),
        "updated_count": len(updated_numbers),
        "updated_numbers": sorted(updated_numbers),
    }


def _parse_args() -> argparse.Namespace:
    return _build_parser().parse_args()


def _build_parser() -> argparse.ArgumentParser:
    parser = ActionableArgumentParser(
        description=(
            "Rewrite bodies of all open issues to the Work Package template."
            " Dry-run by default."
            " WARNING: --apply is destructive and overwrites issue bodies."
        )
    )
    parser.add_argument("--repo", default=None, help="Repo owner/name (default: auto-detect)")
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Apply changes (default: dry-run). "
            "Destructive: overwrites the full body of each affected open issue. "
            "Labels are not modified."
        ),
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    runner = SubprocessGhRunner()

    try:
        repo = args.repo or current_repo(runner)

        result = refactor_open_issues(runner=runner, repo=repo, apply=bool(args.apply))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (GhCliError, ValueError) as exc:
        print_actionable_cli_error(
            exc,
            parser=parser,
            examples=[
                "python -m scripts.github.refactor_open_issues_work_package --repo owner/name",
                "python -m scripts.github.refactor_open_issues_work_package --repo owner/name --apply",
            ],
            see_also=["scripts/github/README.md"],
        )
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
