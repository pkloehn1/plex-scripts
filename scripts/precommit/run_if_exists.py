"""Guard wrapper that skips execution when a target path does not exist.

Slots into the pre-commit wrapper chain::

    run_python -> run_in_repo_venv.py -> run_if_exists.py <guard_path> <command...>

If *guard_path* (resolved relative to the repository root) exists, the
remaining *command* arguments are executed.  If missing, exits 0 with a
skip message — allowing hub-synced hooks to degrade gracefully in repos
that lack the target script or test directory.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath

from scripts.common.paths import repo_root

EXIT_OK = 0
EXIT_USAGE = 2


@dataclass(frozen=True)
class GuardResult:
    """Outcome of the guard check."""

    skipped: bool
    message: str
    exit_code: int


def _is_absolute(path: str) -> bool:
    """Check whether *path* is absolute on any platform."""
    return PurePosixPath(path).is_absolute() or PureWindowsPath(path).is_absolute()


def check_guard(guard_path: str) -> GuardResult:
    """Check whether *guard_path* exists relative to the repository root."""
    if _is_absolute(guard_path):
        return GuardResult(
            skipped=False,
            message=(
                f"Error: guard_path must be relative, got absolute path "
                f"'{guard_path}'. Use a repo-relative path instead "
                f"(e.g. 'scripts/precommit/pytest_affected.py')."
            ),
            exit_code=EXIT_USAGE,
        )
    root = repo_root()
    resolved = root / guard_path
    try:
        resolved.resolve().relative_to(root.resolve())
    except ValueError:
        return GuardResult(
            skipped=False,
            message=(
                f"Error: guard_path escapes the repository root, "
                f"got '{guard_path}'. Use a repo-relative path instead "
                f"(e.g. 'scripts/precommit/pytest_affected.py')."
            ),
            exit_code=EXIT_USAGE,
        )
    if resolved.exists():
        return GuardResult(skipped=False, message="", exit_code=EXIT_OK)
    return GuardResult(
        skipped=True,
        message=f"Skipped: {guard_path} does not exist",
        exit_code=EXIT_OK,
    )


def run_command(command: list[str]) -> int:
    """Execute *command* as a subprocess and return its exit code."""
    if command and command[0].endswith(".py"):
        command = [sys.executable, *command]
    result = subprocess.run(command, check=False)
    return result.returncode


def main(argv: list[str]) -> int:
    """Entry point: ``run_if_exists.py <guard_path> <command...>``."""
    args = argv[1:]
    if len(args) < 2:
        print(
            "Usage: run_if_exists.py <guard_path> <command> [args...]",
            file=sys.stderr,
        )
        return EXIT_USAGE

    guard_path, *command = args
    result = check_guard(guard_path)
    if result.exit_code != EXIT_OK:
        print(result.message, file=sys.stderr)
        return result.exit_code
    if result.skipped:
        print(result.message)
        return result.exit_code

    return run_command(command)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))  # pragma: no cover
