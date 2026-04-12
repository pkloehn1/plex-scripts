#!/usr/bin/env python3
"""Validate that tracked files in governed directories are covered by sync-directives.

Ensures no file slips through sync-directives coverage gaps, which would
cause spoke repositories to silently diverge from the hub.

Extension point: the ``hub_only:`` key in sync-directives.yml lists files
that are intentionally not synced to any spoke.  Entries support glob
patterns (e.g. ``.github/workflows/*.yml``).

The ``governed_roots:`` key lists top-level directory prefixes that must
have complete coverage.  Defaults to prefixes derived from ``files:``
and ``directories:`` entries.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.ci.sync_directives import load_config, resolve_files
from scripts.common.git_runner import GitResult, GitRunner, run_git
from scripts.common.paths import normalize_path, repo_root

_SYNC_DIRECTIVES_PATH = ".github/sync-directives.yml"

_GLOB_CHARS: frozenset[str] = frozenset({"*", "?", "["})


@dataclass(frozen=True)
class Violation:
    """A tracked file not covered by sync-directives."""

    path: Path
    reason: str


def compute_governed_prefixes(
    config: dict[str, Any],
    governed_roots: list[str] | None = None,
) -> list[str]:
    """Extract unique directory prefixes from config and governed_roots.

    Root-level files (no ``/`` in path) are skipped -- they are validated
    only against explicit ``files:`` entries, not by prefix scanning.
    Returns a collapsed list so parent prefixes subsume children.

    When *governed_roots* is provided, those prefixes are included as a
    floor so that new directories under governed roots are always scanned.
    """
    prefixes: set[str] = set()

    for entry in config.get("files", []):
        entry_str = str(entry)
        if "/" in entry_str:
            dir_part = entry_str.rsplit("/", 1)[0] + "/"
            prefixes.add(dir_part)

    for dir_entry in config.get("directories", []):
        dir_path = dir_entry["path"]
        if not dir_path.endswith("/"):
            dir_path += "/"
        prefixes.add(dir_path)

    if governed_roots is not None:
        for root_prefix in governed_roots:
            if not root_prefix.endswith("/"):
                root_prefix += "/"
            prefixes.add(root_prefix)

    sorted_prefixes = sorted(prefixes)
    collapsed: list[str] = []
    for prefix in sorted_prefixes:
        if not any(prefix.startswith(existing) for existing in collapsed):
            collapsed.append(prefix)

    return collapsed


def _check_git_failure(result: GitResult, prefix: str) -> Violation | None:
    """Return a Violation if *result* indicates a git ls-files failure."""
    if result.returncode != 0:
        error_detail = result.stderr.strip() or f"exit code {result.returncode}"
        return Violation(
            path=Path(prefix),
            reason=f"git ls-files failed for prefix '{prefix}': {error_detail}",
        )
    return None


def get_tracked_files(
    prefixes: list[str],
    root: Path,
    runner: GitRunner | None = None,
) -> tuple[set[str], list[Violation]]:
    """Get git-tracked files filtered by directory prefixes.

    Returns a tuple of (tracked files, git error violations).
    """
    run_fn = runner.run_git if runner else run_git

    all_files: set[str] = set()
    errors: list[Violation] = []
    for prefix in prefixes:
        result = run_fn(["ls-files", prefix], cwd=root)
        failure = _check_git_failure(result, prefix)
        if failure is not None:
            errors.append(failure)
            continue
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if stripped:
                all_files.add(normalize_path(stripped))

    return all_files, errors


def expand_hub_only(raw_entries: list[str], root: Path) -> set[str]:
    """Expand hub_only entries, resolving glob patterns against *root*.

    Literal paths (no glob metacharacters) are kept as-is even if the
    file does not exist yet.  Glob patterns are expanded via
    :py:meth:`pathlib.Path.glob`.  All entries are normalized for
    cross-platform path comparison.
    """
    result: set[str] = set()

    for entry in raw_entries:
        if _GLOB_CHARS & set(entry):
            for match in root.glob(entry):
                if match.is_file():
                    result.add(normalize_path(str(match.relative_to(root))))
        else:
            result.add(normalize_path(entry))

    return result


def check_completeness(
    config: dict[str, Any],
    root: Path,
    runner: GitRunner | None = None,
) -> list[Violation]:
    """Return violations for tracked files not covered by sync-directives."""
    covered = set(resolve_files(root, config))
    governed_roots = config.get("governed_roots")
    prefixes = compute_governed_prefixes(config, governed_roots)

    if not prefixes:
        return []

    tracked, git_errors = get_tracked_files(prefixes, root, runner)
    if git_errors:
        return git_errors

    hub_only = expand_hub_only(config.get("hub_only") or [], root)

    uncovered = sorted(tracked - covered - hub_only)

    return [
        Violation(
            path=Path(file_path),
            reason="not listed in sync-directives files:, directories:, or hub_only:",
        )
        for file_path in uncovered
    ]


def main() -> int:
    """Entry point for the pre-commit hook."""
    root = repo_root()
    config_path = root / _SYNC_DIRECTIVES_PATH

    if not config_path.is_file():
        return 0

    config = load_config(config_path)
    violations = check_completeness(config, root)

    if not violations:
        return 0

    sys.stderr.write(
        "\nERROR: sync-directives completeness check failed.\n"
        "The following tracked files are not covered by "
        ".github/sync-directives.yml:\n\n"
    )
    for violation in violations:
        display_path = normalize_path(str(violation.path))
        sys.stderr.write(f"  - {display_path}: {violation.reason}\n")
    sys.stderr.write(
        "\nTo fix, add each file to one of:\n"
        "  - files: (individual file entry)\n"
        "  - directories: (directory pattern entry)\n"
        "  - hub_only: (intentionally not synced)\n"
    )
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
