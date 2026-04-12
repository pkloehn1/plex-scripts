#!/usr/bin/env python3
"""Pre-commit hook to block commits from worktrees and unexpected locations.

Validates two conditions:

1.  The repository is not a git worktree (worktrees cause VS Code/GitHub
    integration confusion).
2.  The repository is cloned under the user's home directory.

Exit codes:
    0: Valid location (commit allowed)
    1: Invalid location (commit blocked)
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _run_git(args: list[str]) -> tuple[int, str, str]:
    """Run a git command and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _is_worktree() -> tuple[bool, str | None]:
    """Check if the current directory is a git worktree.

    Returns:
        Tuple of (is_worktree, worktree_path_or_none)
    """
    returncode, git_dir, _ = _run_git(["rev-parse", "--git-dir"])
    if returncode != 0:
        return False, None

    git_dir_path = Path(git_dir).resolve()
    # In a worktree, .git is a file pointing to the main repo's .git/worktrees/{name}
    if git_dir_path.is_file():
        return True, str(git_dir_path)
    # Check if we're in .git/worktrees/{name} with the expected order
    parts = git_dir_path.parts
    for idx in range(len(parts) - 1):
        if parts[idx] == ".git" and parts[idx + 1] == "worktrees":
            return True, str(git_dir_path)
    if ".git" in parts and "worktrees" in parts:
        return False, str(git_dir_path)

    return False, None


def _get_repo_root() -> Path | None:
    """Get the repository root directory."""
    returncode, repo_root, _ = _run_git(["rev-parse", "--show-toplevel"])
    if returncode != 0:
        return None
    return Path(repo_root).resolve()


def check_repo_location() -> tuple[bool, str]:
    """Check if the repository location is valid.

    Returns:
        Tuple of (is_valid, message)
    """
    # Check if we're in a worktree
    is_wt, wt_path = _is_worktree()
    if is_wt:
        return (
            False,
            f"Commits are blocked from git worktrees. Detected worktree at: {wt_path}",
        )

    # Get the repository root
    repo_root = _get_repo_root()
    if not repo_root:
        return False, "Unable to determine repository root"

    # Verify the repo is under the user's home directory
    home = Path.home()
    try:
        repo_root.relative_to(home)
    except ValueError:
        return (
            False,
            f"Repository is outside your home directory.\n  Clone path: {repo_root}\n  Expected under: {home}",
        )

    return True, f"Repository location is valid: {repo_root}"


def main() -> int:
    """Main entry point."""
    # Allow skipping this check via environment variable
    if "SKIP_REPO_LOCATION_CHECK" in os.environ:
        return 0

    is_valid, message = check_repo_location()

    if is_valid:
        return 0

    print("=" * 70)
    print("ERROR: Invalid repository location")
    print("=" * 70)
    print(f"\n{message}\n")
    print(
        "Commits from git worktrees and clones outside your home directory "
        "are blocked. Clone the repository under your user profile."
    )
    print("\nSee: docs/repository-standards/devsecops-workflow.md")
    print("=" * 70)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
