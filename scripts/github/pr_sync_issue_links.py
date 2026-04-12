#!/usr/bin/env python3
"""Sync "Closes #..." / "Relates to #..." lines in a PR body.

Use case:
- Keep PR bodies deterministic for automation by normalizing issue auto-close lines.
- Avoid shell quoting pitfalls when updating multi-line PR bodies.

Behavior:
- Removes any existing lines that start with:
    - "Closes #"
    - "Relates to #"
    (wherever they appear in the body)
- Appends canonical issue lines at the end of the body.

This script updates PR bodies via `gh api` (PATCH /pulls/{number}).
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Any

from scripts.github.gh_cli import (
    ActionableArgumentParser,
    GhRunner,
    active_pr_number,
    current_repo,
    parse_repo,
    run_actionable_main,
    run_json,
)

_CLOSE_TOKENS = ("Closes",)
_RELATES_TOKENS = ("Relates", "to")
_LINKED_ISSUE_PREFIX = "Linked Issue:"


@dataclass(frozen=True)
class SyncResult:
    repo: str
    pr: int
    closes: list[int]
    relates: list[int]
    changed: bool


def _parse_positive_int(value: str) -> int:
    try:
        out = int(value)
    except ValueError as exc:
        raise ValueError("issue number must be an integer") from exc
    if out <= 0:
        raise ValueError("issue number must be positive")
    return out


def _strip_issue_link_lines(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        if line.startswith(_LINKED_ISSUE_PREFIX):
            continue
        if _try_parse_close_line(line) is not None:
            continue
        if _try_parse_relate_line(line) is not None:
            continue
        out.append(line)
    return out


def _normalize_newlines(text: str) -> list[str]:
    # Keep stable behavior across platforms; strip trailing CR if present.
    return [line.rstrip("\r") for line in text.splitlines()]


def _try_parse_issue_num_token(token: str) -> int | None:
    if not token.startswith("#"):
        return None
    digits = token[1:]
    if not digits.isdigit():
        return None
    num = int(digits)
    return num if num > 0 else None


def _try_parse_close_line(line: str) -> int | None:
    tokens = line.strip().split()
    if len(tokens) != 2 or tokens[0] != _CLOSE_TOKENS[0]:
        return None
    return _try_parse_issue_num_token(tokens[1])


def _try_parse_relate_line(line: str) -> int | None:
    tokens = line.strip().split()
    if len(tokens) != 3 or tuple(tokens[:2]) != _RELATES_TOKENS:
        return None
    return _try_parse_issue_num_token(tokens[2])


def _extract_issue_links(lines: list[str]) -> tuple[set[int], set[int]]:
    closes: set[int] = set()
    relates: set[int] = set()

    for line in lines:
        close_num = _try_parse_close_line(line)
        if close_num is not None:
            closes.add(close_num)
            continue

        relate_num = _try_parse_relate_line(line)
        if relate_num is not None:
            relates.add(relate_num)

    return closes, relates


def sync_issue_links_in_body(
    *,
    body: str | None,
    closes: set[int],
    relates: set[int],
) -> str:
    raw = body or ""
    existing_lines = _normalize_newlines(raw)

    remaining = _strip_issue_link_lines(existing_lines)

    # Avoid leaving leading/trailing whitespace-only lines behind after removing
    # issue-link lines.
    while remaining and remaining[0].strip() == "":
        remaining.pop(0)
    while remaining and remaining[-1].strip() == "":
        remaining.pop()

    link_lines: list[str] = []
    for issue_num in sorted(closes):
        link_lines.append(f"Closes #{issue_num}")
    for issue_num in sorted(relates):
        link_lines.append(f"Relates to #{issue_num}")

    # Ensure a blank line before the issue block if there is existing content.
    new_lines = list(remaining)
    if link_lines:
        if new_lines and new_lines[-1].strip() != "":
            new_lines.append("")
        new_lines.extend(link_lines)

    # Ensure exactly one trailing newline for stable diffs in GitHub UI.
    return "\n".join(new_lines).rstrip("\n") + "\n"


def _fetch_pr(*, runner: GhRunner, repo: str, pr_number: int) -> dict[str, Any]:
    owner, name = parse_repo(repo)
    payload = run_json(
        runner,
        [
            "gh",
            "api",
            f"/repos/{owner}/{name}/pulls/{pr_number}",
        ],
    )
    if not isinstance(payload, dict):
        raise ValueError("Unexpected PR payload")
    return payload


def _update_pr_body(*, runner: GhRunner, repo: str, pr_number: int, body: str) -> dict[str, Any]:
    owner, name = parse_repo(repo)
    payload = run_json(
        runner,
        [
            "gh",
            "api",
            "--method",
            "PATCH",
            f"/repos/{owner}/{name}/pulls/{pr_number}",
            "-f",
            f"body={body}",
        ],
    )
    if not isinstance(payload, dict):
        raise ValueError("Unexpected PR payload")
    return payload


def _fetch_pr_body(*, runner: GhRunner, repo: str, pr_number: int) -> str:
    """Fetch the current PR body as a string."""
    payload = _fetch_pr(runner=runner, repo=repo, pr_number=pr_number)
    body = payload.get("body")
    return body if isinstance(body, str) else ""


def sync_pr_issue_links(
    *,
    runner: GhRunner,
    repo: str,
    pr_number: int,
    closes: set[int],
    relates: set[int],
    dry_run: bool,
    merge_existing: bool,
) -> SyncResult:
    pr_payload = _fetch_pr(runner=runner, repo=repo, pr_number=pr_number)
    old_body = pr_payload.get("body") if isinstance(pr_payload.get("body"), str) else ""

    if merge_existing:
        existing_closes, existing_relates = _extract_issue_links(_normalize_newlines(old_body or ""))
        closes = set(closes) | existing_closes
        relates = set(relates) | existing_relates

    new_body = sync_issue_links_in_body(body=old_body, closes=closes, relates=relates)
    changed = new_body != (old_body or "")

    if changed and not dry_run:
        _update_pr_body(runner=runner, repo=repo, pr_number=pr_number, body=new_body)

    return SyncResult(
        repo=repo,
        pr=pr_number,
        closes=sorted(closes),
        relates=sorted(relates),
        changed=changed,
    )


def _parse_args() -> argparse.Namespace:
    return _build_parser().parse_args()


def _build_parser() -> argparse.ArgumentParser:
    parser = ActionableArgumentParser(description="Sync Closes/Relates issue lines in a PR body.")
    parser.add_argument("--repo", default=None, help="Repo owner/name (default: auto-detect)")
    parser.add_argument("--pr", type=int, default=None, help="PR number (default: active PR)")
    parser.add_argument(
        "--close",
        action="append",
        default=None,
        help="Issue number to add as 'Closes #N' (repeatable)",
    )
    parser.add_argument(
        "--relate",
        action="append",
        default=None,
        help="Issue number to add as 'Relates to #N' (repeatable)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Compute changes but do not patch")
    parser.add_argument(
        "--merge-existing",
        action="store_true",
        help=(
            "Merge existing Closes/Relates lines from the current PR body with the provided ones. "
            "Use this to add a single issue without re-listing the full set."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    parser.add_argument(
        "--auto-summary",
        dest="auto_summary",
        action="store_true",
        default=False,
        help="Also refresh auto-summary markers in the PR body from branch commits",
    )
    parser.add_argument(
        "--base-branch",
        dest="base_branch",
        default=None,
        help="Base branch for --auto-summary commit range (default: auto-detect)",
    )
    return parser


def _refresh_auto_summary(
    *,
    gh_runner: GhRunner,
    repo: str,
    pr_number: int,
    base_branch: str | None,
    dry_run: bool,
) -> None:
    """Refresh auto-summary markers in the PR body from branch commits."""
    from pathlib import Path

    from scripts.common.git_runner import GitResult
    from scripts.common.git_runner import run_git as _run_git
    from scripts.github.pr_auto_summary import refresh_auto_summary_in_body

    class _DefaultGitRunner:
        def run_git(self, git_args: list[str], *, cwd: Path | None = None) -> GitResult:
            return _run_git(git_args, cwd=cwd)

    current_body = _fetch_pr_body(runner=gh_runner, repo=repo, pr_number=pr_number)
    updated_body = refresh_auto_summary_in_body(
        existing_body=current_body,
        git_runner=_DefaultGitRunner(),
        base_branch=base_branch,
    )
    if updated_body != current_body and not dry_run:
        _update_pr_body(runner=gh_runner, repo=repo, pr_number=pr_number, body=updated_body)


def _run(args: argparse.Namespace, _parser: argparse.ArgumentParser, runner: GhRunner) -> int:
    repo = args.repo or current_repo(runner)
    pr_number = args.pr or active_pr_number(runner)

    closes = {_parse_positive_int(arg) for arg in (args.close or []) if isinstance(arg, str)}
    relates = {_parse_positive_int(arg) for arg in (args.relate or []) if isinstance(arg, str)}

    result = sync_pr_issue_links(
        runner=runner,
        repo=repo,
        pr_number=pr_number,
        closes=closes,
        relates=relates,
        dry_run=bool(args.dry_run),
        merge_existing=bool(args.merge_existing),
    )

    if args.auto_summary:
        _refresh_auto_summary(
            gh_runner=runner,
            repo=repo,
            pr_number=pr_number,
            base_branch=args.base_branch,
            dry_run=bool(args.dry_run),
        )

    if args.json:
        print(json.dumps(result.__dict__, indent=2, sort_keys=True))
    else:
        _print_human_summary(result=result, dry_run=bool(args.dry_run))

    return 0


def main() -> int:
    return run_actionable_main(
        build_parser=_build_parser,
        handler=_run,
        examples=[
            "python -m scripts.github.pr_sync_issue_links --repo owner/name --pr 123 --close 456 --relate 789",
            "python -m scripts.github.pr_sync_issue_links --repo owner/name --pr 123 --close 456 --merge-existing",
        ],
        see_also=["scripts/github/README.md"],
    )


def _print_human_summary(*, result: SyncResult, dry_run: bool) -> None:
    if not result.changed:
        print(f"No changes needed for PR #{result.pr}.")
        return

    verb = "Would update" if dry_run else "Updated"
    print(f"{verb} PR #{result.pr} issue links.")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
