from __future__ import annotations

import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class GitResult:
    """Typed result from a git command."""

    returncode: int
    stdout: str
    stderr: str

    def __iter__(self) -> Iterator[int | str]:
        """Allow tuple unpacking: ``code, out, err = run_git(...)``."""
        yield self.returncode
        yield self.stdout
        yield self.stderr


class GitRunner(Protocol):
    """Protocol for git command execution (enables test stubs)."""

    def run_git(self, args: list[str], *, cwd: Path | None = None) -> GitResult: ...


def run_git(
    args: list[str],
    *,
    cwd: Path | None = None,
) -> GitResult:
    """Run a git command and return a :class:`GitResult`.

    Returns exit code 127 if git is not on PATH.
    """
    try:
        proc = subprocess.run(
            ["git", *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(cwd) if cwd is not None else None,
        )
    except FileNotFoundError:
        return GitResult(127, "", "git not found on PATH")
    return GitResult(proc.returncode, proc.stdout, proc.stderr)
