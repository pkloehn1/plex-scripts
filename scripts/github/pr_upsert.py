#!/usr/bin/env python3
"""Create or edit GitHub pull requests via `gh api`.

- Create: omit --number (POST /pulls)
- Edit: provide --number (PATCH /pulls/{number})

Notes:
- For create, `head` must be a branch ref visible to GitHub (often "owner:branch").
- This script does not perform git operations (no push, no branch creation).
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


def _pr_method_endpoint(
    *,
    owner: str,
    name: str,
    number: int | None,
    title: str | None,
    base: str | None,
    head: str | None,
) -> tuple[str, str]:
    if number is None:
        if not isinstance(title, str) or not title.strip():
            raise ValueError("--title is required when creating a PR")
        if not isinstance(base, str) or not base.strip():
            raise ValueError("--base is required when creating a PR")
        if not isinstance(head, str) or not head.strip():
            raise ValueError("--head is required when creating a PR")
        return "POST", f"/repos/{owner}/{name}/pulls"

    if number <= 0:
        raise ValueError("--number must be a positive integer")
    return "PATCH", f"/repos/{owner}/{name}/pulls/{number}"


def _fetch_pr(*, runner: GhRunner, repo: str, number: int) -> dict[str, Any]:
    owner, name = parse_repo(repo)
    payload = run_json(
        runner,
        [
            "gh",
            "api",
            f"/repos/{owner}/{name}/pulls/{number}",
        ],
    )
    if not isinstance(payload, dict):
        raise ValueError("Unexpected PR payload")
    return payload


def _mark_pr_ready_for_review(*, runner: GhRunner, repo: str, number: int) -> None:
    """Convert a draft PR to ready-for-review if needed.

    GitHub requires a dedicated endpoint for this transition.
    """
    pr_data = _fetch_pr(runner=runner, repo=repo, number=number)
    is_draft = pr_data.get("draft") if isinstance(pr_data.get("draft"), bool) else False
    if not is_draft:
        return

    owner, name = parse_repo(repo)
    # POST /pulls/{pull_number}/ready_for_review
    run_json(
        runner,
        [
            "gh",
            "api",
            "--method",
            "POST",
            f"/repos/{owner}/{name}/pulls/{number}/ready_for_review",
        ],
    )


def upsert_pr(
    *,
    runner: GhRunner,
    repo: str,
    number: int | None,
    title: str | None,
    body: str | None,
    base: str | None,
    head: str | None,
) -> dict[str, Any]:
    owner, name = parse_repo(repo)

    method, endpoint = _pr_method_endpoint(
        owner=owner,
        name=name,
        number=number,
        title=title,
        base=base,
        head=head,
    )

    argv: list[str] = ["gh", "api", "--method", method, endpoint]

    if title is not None:
        argv.extend(["-f", f"title={title}"])
    if body is not None:
        argv.extend(["-f", f"body={body}"])

    # Only valid on create, but safe to include on edit only if supplied.
    if base is not None:
        argv.extend(["-f", f"base={base}"])
    if head is not None:
        argv.extend(["-f", f"head={head}"])

    payload = run_json(runner, argv)
    if not isinstance(payload, dict):
        raise ValueError("Unexpected PR payload")
    return payload


def _parse_args() -> argparse.Namespace:
    return _build_parser().parse_args()


def _build_parser() -> argparse.ArgumentParser:
    parser = ActionableArgumentParser(description="Create or edit a GitHub pull request.")
    parser.add_argument("--repo", default=None, help="Repo owner/name (default: auto-detect)")
    parser.add_argument("--number", type=int, help="PR number (edit mode)")
    parser.add_argument("--title", help="PR title")
    parser.add_argument("--body", help="PR body")
    parser.add_argument("--body-file", type=Path, help="Path to PR body file")
    parser.add_argument("--base", help="Base branch (create mode)")
    parser.add_argument("--head", help="Head branch (create mode)")
    parser.add_argument(
        "--ready-for-review",
        dest="ready_for_review",
        action="store_true",
        default=False,
        help="If the PR is currently a draft, mark it ready for review (edit mode)",
    )
    parser.add_argument(
        "--no-draft",
        dest="ready_for_review",
        action="store_true",
        default=False,
        help="Alias for --ready-for-review (edit mode)",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    parser.add_argument(
        "--auto-summary",
        dest="auto_summary",
        action="store_true",
        default=False,
        help="Auto-generate PR body from branch commits (requires no --body/--body-file)",
    )
    parser.add_argument(
        "--base-branch",
        dest="base_branch",
        default=None,
        help="Base branch for --auto-summary commit range (default: auto-detect)",
    )
    parser.add_argument(
        "--issue",
        type=int,
        action="append",
        default=None,
        help="Issue number(s) for Linked Issues section (repeatable, used with --auto-summary)",
    )
    return parser


def _resolve_auto_summary_body(
    args: argparse.Namespace,
    *,
    explicit_body: str | None,
    gh_runner: GhRunner,
    repo: str,
) -> str | None:
    """Generate or update PR body via auto-summary when enabled.

    Returns the body to use (auto-generated, updated, or the original).
    """
    if not args.auto_summary:
        return explicit_body
    if explicit_body is not None:
        raise ValueError("--auto-summary cannot be combined with --body or --body-file")

    from scripts.common.git_runner import run_git as git_run_git
    from scripts.github.pr_auto_summary import (
        detect_base_branch,
        generate_auto_summary,
        get_branch_commits,
        replace_auto_summary_blocks,
    )

    class _GitRunner:
        def run_git(self, git_args: list[str], *, cwd: Path | None = None) -> Any:
            return git_run_git(git_args, cwd=cwd)

    git_runner = _GitRunner()
    base = args.base_branch or detect_base_branch(runner=git_runner)
    commits = get_branch_commits(runner=git_runner, base_branch=base)
    issue_nums = list(args.issue) if args.issue else None
    summary = generate_auto_summary(commits, issue_numbers=issue_nums)

    # Edit mode: update only auto-generated sections in existing body.
    if args.number is not None:
        existing_pr = _fetch_pr(runner=gh_runner, repo=repo, number=args.number)
        existing_body = existing_pr.get("body") or ""
        if isinstance(existing_body, str) and existing_body.strip():
            updated = replace_auto_summary_blocks(
                existing_body,
                new_summary_md=summary.summary_md,
            )
            if issue_nums:
                from scripts.github.pr_sync_issue_links import sync_issue_links_in_body

                updated = sync_issue_links_in_body(
                    body=updated,
                    closes=set(issue_nums),
                    relates=set(),
                )
            return updated

    return summary.full_body


def _run(args: argparse.Namespace, _parser: argparse.ArgumentParser, runner: GhRunner) -> int:
    repo = resolve_repo(args, runner)
    body = resolve_body(args)

    body = _resolve_auto_summary_body(
        args,
        explicit_body=body,
        gh_runner=runner,
        repo=repo,
    )

    if args.ready_for_review and args.number is None:
        raise ValueError("--ready-for-review is only valid with --number")

    pr_data = upsert_pr(
        runner=runner,
        repo=repo,
        number=args.number,
        title=args.title,
        body=body,
        base=args.base,
        head=args.head,
    )

    pr_number = pr_data.get("number")
    if args.ready_for_review and isinstance(pr_number, int) and pr_number > 0:
        _mark_pr_ready_for_review(runner=runner, repo=repo, number=pr_number)
        pr_data = _fetch_pr(runner=runner, repo=repo, number=pr_number)

    number = pr_data.get("number")
    url = pr_data.get("html_url")

    result = {
        "repo": repo,
        "number": number,
        "url": url,
        "title": pr_data.get("title"),
        "state": pr_data.get("state"),
        "draft": pr_data.get("draft"),
    }

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"PR #{number}: {url}")

    return 0


def main() -> int:
    return run_actionable_main(
        build_parser=_build_parser,
        handler=_run,
        examples=[
            'python -m scripts.github.pr_upsert --repo owner/name --title "My PR" --body-file .github/pull_request_template.md --base main --head feature/foo',
            "python -m scripts.github.pr_upsert --repo owner/name --number 123 --ready-for-review",
        ],
        see_also=["scripts/github/README.md"],
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
