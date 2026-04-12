#!/usr/bin/env python3
"""Delete a remote branch on GitHub.

Why this exists:
- Repo policy is to interact with GitHub via `scripts/github/*` helpers rather than
    calling `gh` directly.
- Used for cleaning up automation-created branches after PR cleanup.

Implementation:
- Uses GitHub REST: DELETE /repos/{owner}/{repo}/git/refs/heads/{branch}
"""

from __future__ import annotations

import argparse
import json
import re
from typing import Any

from scripts.github.cli_utils import resolve_repo
from scripts.github.gh_cli import (
    ActionableArgumentParser,
    GhCliError,
    GhRunner,
    SubprocessGhRunner,
    parse_repo,
    print_actionable_cli_error,
    run_text,
)

_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$")


def _validate_branch(branch: str) -> str:
    branch_name = branch.strip()
    if not branch_name:
        raise ValueError("branch is required")
    if branch_name.startswith("refs/"):
        raise ValueError("branch must be a branch name, not a full ref (no 'refs/...')")
    if branch_name.startswith("/") or branch_name.endswith("/") or "//" in branch_name:
        raise ValueError("branch must not start/end with '/' or contain '//'")
    if not _BRANCH_RE.fullmatch(branch_name):
        raise ValueError("branch contains invalid characters")
    return branch_name


def delete_branch(
    *,
    runner: GhRunner,
    repo: str,
    branch: str,
) -> dict[str, Any]:
    owner, name = parse_repo(repo)
    branch_name = _validate_branch(branch)

    endpoint = f"/repos/{owner}/{name}/git/refs/heads/{branch_name}"
    argv = ["gh", "api", "--method", "DELETE", endpoint]

    # GitHub returns 204 No Content; gh prints "null".
    raw = run_text(runner, argv)

    return {
        "ok": True,
        "argv": argv,
        "repo": repo,
        "branch": branch_name,
        "stdout": raw.strip(),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = ActionableArgumentParser(description="Delete a remote branch on GitHub.")
    parser.add_argument("--repo", default=None, help="Repo owner/name (default: auto-detect)")
    parser.add_argument("--branch", required=True, help="Branch name (e.g., feature/foo)")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    return parser


def main() -> int:  # pragma: no cover
    parser = _build_parser()
    args = parser.parse_args()
    runner = SubprocessGhRunner()

    try:
        repo = resolve_repo(args, runner)
        payload = delete_branch(runner=runner, repo=repo, branch=args.branch)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"Deleted branch {args.branch} in {repo}.")
        return 0
    except (GhCliError, ValueError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
        else:
            print_actionable_cli_error(
                exc,
                parser=parser,
                examples=[
                    "python -m scripts.github.delete_branch --repo owner/name --branch feature/foo",
                ],
                see_also=["scripts/github/README.md"],
            )
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
