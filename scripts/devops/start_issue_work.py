#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    url: str | None


def repo_root() -> Path:
    from scripts.common.paths import repo_root as _repo_root

    return _repo_root()


def slugify(text: str, *, max_words: int = 6) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", " ", text).strip().lower()
    words = [word for word in cleaned.split() if word]
    return "-".join(words[:max_words]) or "work"


def parse_conventional_title(title: str) -> tuple[str | None, str | None, str]:
    """Parse a Conventional Commits-style title.

    Supported forms:
    - type(scope): summary
    - type: summary

    If the title does not match, returns (None, None, <original stripped title>).
    """
    raw = title.strip()
    if not raw:
        return None, None, raw

    # Must contain exactly a ':' separator and at least one whitespace char after it.
    # (matches the previous regex behavior requiring `:\s+`)
    if ":" not in raw:
        return None, None, raw

    left, right = raw.split(":", 1)
    if not right or not right[0].isspace():
        return None, None, raw

    summary = right.strip()
    if not summary:
        return None, None, raw  # pragma: no cover

    left = left.strip()
    if not left:
        return None, None, raw

    scope: str | None = None
    typ = left

    if left.endswith(")") and "(" in left:
        open_idx = left.find("(")
        typ = left[:open_idx]
        scope = left[open_idx + 1 : -1]

        if not scope:
            return None, None, raw

    typ = typ.strip()
    if not typ or not typ.isalpha() or not typ.islower():
        return None, None, raw

    return typ, scope, summary


def default_type_for_title(title: str) -> str:
    title_l = title.lower()
    if "docs" in title_l:
        return "docs"
    if "fix" in title_l:
        return "fix"
    if "refactor" in title_l:
        return "refactor"
    if "security" in title_l:
        return "security"
    if "test" in title_l:
        return "test"
    return "chore"


def default_scope_for_title(title: str) -> str:
    title_l = title.lower()
    if "pre-commit" in title_l or "precommit" in title_l:
        return "ci"
    if "label" in title_l or "workflow" in title_l or "github" in title_l:
        return "ci"
    if "devsecops" in title_l:
        return "devsecops"
    return "repo"


def build_branch_name(*, issue_number: int, issue_title: str) -> str:
    typ, scope, summary = parse_conventional_title(issue_title)

    branch_type = typ or default_type_for_title(issue_title)
    branch_scope = slugify(scope or default_scope_for_title(issue_title), max_words=3)

    short_slug = slugify(summary, max_words=6)
    return f"{branch_type}/{issue_number}-{branch_scope}-{short_slug}"


def build_git_branch_commands(*, branch: str) -> list[list[str]]:
    # Intentionally no `git push` anywhere in this helper.
    return [["git", "checkout", "-b", branch]]


def _run(argv: list[str], *, cwd: Path) -> str:
    proc = subprocess.run(
        argv,
        cwd=str(cwd),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        msg = stderr or stdout or "command failed"
        raise RuntimeError(f"{argv!r}: {msg}")
    return proc.stdout


def ensure_clean_working_tree(*, cwd: Path) -> None:
    out = _run(["git", "status", "--porcelain=v1"], cwd=cwd).strip()
    if out:
        raise RuntimeError("Working tree is not clean. Commit/stash changes first.")


def ensure_on_main(*, cwd: Path) -> None:
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd).strip()
    if branch != "main":
        raise RuntimeError(f"Refusing to branch from {branch!r}. Checkout 'main' first, or pass --allow-non-main.")


def fetch_issue_via_gh_api_call(*, repo: str, number: int, cwd: Path) -> Issue:
    argv = [
        sys.executable,
        "-m",
        "scripts.github.gh_api_call",
        "--repo",
        repo,
        "--op",
        "issue",
        "--number",
        str(number),
    ]
    raw = _run(argv, cwd=cwd)
    payload = json.loads(raw)

    if not isinstance(payload, dict) or not payload.get("ok"):
        raise RuntimeError("Failed to fetch issue via gh_api_call")

    issue = payload.get("json")
    if not isinstance(issue, dict):
        raise RuntimeError("Unexpected issue payload")

    title = issue.get("title")
    if not isinstance(title, str) or not title.strip():
        raise RuntimeError("Issue payload missing title")

    url = issue.get("html_url")
    if not isinstance(url, str) or not url.strip():
        url = None

    return Issue(number=number, title=title.strip(), url=url)


def print_next_steps(*, issue: Issue, branch: str) -> None:
    print(f"Issue #{issue.number}: {issue.title}")
    if issue.url:
        print(f"URL: {issue.url}")
    print(f"Branch: {branch}")
    print()
    print("Next steps:")
    print("- Review acceptance criteria and scope")
    print("- Implement smallest changes + add tests")
    print("- Run pre-commit once via git commit")
    print("- Push branch (user) and open PR via scripts/github helpers")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bootstrap local work for a GitHub issue: fetch issue, create branch, print next steps."
    )
    parser.add_argument("--repo", required=True, help="GitHub repo (owner/name)")
    parser.add_argument("--issue", type=int, required=True, help="Issue number")
    parser.add_argument("--dry-run", action="store_true", help="Print actions but do not run git")
    parser.add_argument(
        "--allow-non-main",
        action="store_true",
        help="Allow branching from the current branch (default requires main)",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    if args.issue <= 0:
        print("--issue must be a positive integer", file=sys.stderr)
        return EXIT_USAGE

    cwd = repo_root()

    try:
        ensure_clean_working_tree(cwd=cwd)
        if not args.allow_non_main:
            ensure_on_main(cwd=cwd)

        issue = fetch_issue_via_gh_api_call(repo=args.repo, number=args.issue, cwd=cwd)
        branch = build_branch_name(issue_number=issue.number, issue_title=issue.title)

        cmds = build_git_branch_commands(branch=branch)
        if args.dry_run:
            for cmd in cmds:
                print(" ".join(cmd))
        else:
            for cmd in cmds:
                _run(cmd, cwd=cwd)

        print_next_steps(issue=issue, branch=branch)
        return EXIT_OK
    except (RuntimeError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
