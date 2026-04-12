from __future__ import annotations

from pathlib import Path

from scripts.common import git_runner
from scripts.common.git_runner import GitResult


def run_git(args: list[str]) -> GitResult:
    """Run a git command and return a GitResult."""
    return git_runner.run_git(args)


def get_staged_paths(*path_filters: str) -> tuple[list[Path], list[str]]:
    """Return staged paths, optionally filtered by path prefixes."""
    args = ["diff", "--cached", "--name-only", "--diff-filter=ACMR"]
    if path_filters:
        args.append("--")
        args.extend(path_filters)
    result = run_git(args)
    if result.returncode != 0:
        return [], [f"git diff --cached failed: {result.stderr.strip() or 'unknown error'}"]
    paths = [Path(line.strip()) for line in result.stdout.splitlines() if line.strip()]
    return paths, []


def read_staged_file(path: Path) -> tuple[str | None, str | None]:
    """Read staged content of a file via git show."""
    result = run_git(["show", f":{path.as_posix()}"])
    if result.returncode != 0:
        return None, f"git show :{path} failed: {result.stderr.strip() or 'unknown error'}"
    return result.stdout, None
