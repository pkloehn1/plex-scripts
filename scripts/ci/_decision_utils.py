"""Shared utilities for CI lint-decision scripts.

Each ``should_run_lint_*.py`` script decides whether a heavy linter should run
based on a list of changed files.  The path normalisation, file reading, and
glob-matching logic is identical across scripts and lives here.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable
from dataclasses import dataclass

from scripts.common.paths import normalize_path, repo_root


@dataclass(frozen=True)
class DecisionResult:
    """Typed result from a CI lint-decision check."""

    should_run: bool
    reason: str
    matched_paths: tuple[str, ...]


def read_changed_files() -> list[str]:
    """Read ``changed-files.txt`` from the repository root.

    Raises :class:`FileNotFoundError` when the file does not exist and
    :class:`OSError` on other I/O failures.  Callers should catch
    :class:`OSError` and fall back to a safe default.
    """
    changed_files_path = repo_root() / "changed-files.txt"
    resolved = changed_files_path.resolve()

    if not changed_files_path.exists():
        raise FileNotFoundError(str(changed_files_path))

    with resolved.open(encoding="utf-8") as file_handle:
        return [line.strip() for line in file_handle.read().splitlines() if line.strip()]


def decide(changed_paths: Iterable[str], relevant_globs: tuple[str, ...]) -> DecisionResult:
    """Decide whether a linter should run based on changed paths.

    Returns a :class:`DecisionResult` with the decision, reason, and matched paths.
    """
    normalized = [normalize_path(path_item) for path_item in changed_paths if path_item and path_item.strip()]
    matched: list[str] = []
    for path in normalized:
        for glob in relevant_globs:
            if fnmatch.fnmatchcase(path, glob):
                matched.append(path)
                break
    if matched:
        return DecisionResult(
            should_run=True,
            reason="relevant files changed",
            matched_paths=tuple(matched),
        )
    return DecisionResult(
        should_run=False,
        reason="no relevant files changed",
        matched_paths=(),
    )


def should_run(changed_paths: Iterable[str], relevant_globs: tuple[str, ...]) -> bool:
    """Return *True* when any *changed_paths* match a *relevant_globs* pattern."""
    return decide(changed_paths, relevant_globs).should_run
