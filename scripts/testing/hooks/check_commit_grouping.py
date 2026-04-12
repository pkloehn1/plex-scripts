#!/usr/bin/env python3
"""Block commits that mix commit tooling with other changes.

Rules:
- If .pre-commit-config.yaml is staged, it must be committed alone.
- Commit tooling files must not be staged with non-tooling changes.

Commit tooling paths:
- .pre-commit-config.yaml
- scripts/precommit/**
- scripts/testing/hooks/**
"""

from __future__ import annotations

import sys
from pathlib import Path

from scripts.testing.hooks.git_utils import get_staged_paths as _get_staged_paths

COMMIT_TOOLING_ROOTS = (
    "scripts/precommit/",
    "scripts/testing/hooks/",
)


def _is_commit_tooling_path(path: Path) -> bool:
    path_str = path.as_posix()
    if path_str == ".pre-commit-config.yaml":
        return True
    return any(path_str.startswith(root) for root in COMMIT_TOOLING_ROOTS)


def _format_path_list(title: str, paths: list[Path]) -> str:
    if not paths:
        return ""
    lines = "\n".join(f"  - {path.as_posix()}" for path in sorted(paths, key=lambda item: item.as_posix()))
    return f"\n{title}:\n{lines}\n"


def _emit_pre_commit_config_error(commit_tooling: list[Path], other: list[Path]) -> None:
    sys.stderr.write("\nERROR: Commit blocked: .pre-commit-config.yaml must be committed alone first.\n")
    sys.stderr.write(_format_path_list("Staged commit tooling files", commit_tooling))
    if other:
        sys.stderr.write(_format_path_list("Staged other files", other))
    sys.stderr.write(
        "\nRequired order:\n"
        "  1. Commit .pre-commit-config.yaml alone.\n"
        "  2. Commit remaining commit-tooling files (if any).\n"
        "  3. Commit other changes.\n"
    )


def _emit_mixed_tooling_error(commit_tooling: list[Path], other: list[Path]) -> None:
    sys.stderr.write("\nERROR: Commit blocked: commit tooling files must be committed separately.\n")
    sys.stderr.write(_format_path_list("Staged commit tooling files", commit_tooling))
    sys.stderr.write(_format_path_list("Staged other files", other))
    sys.stderr.write(
        "\nRequired order:\n"
        "  1. Commit commit-tooling files (no non-tooling files staged).\n"
        "  2. Commit other changes.\n"
    )


def main() -> int:
    paths, errors = _get_staged_paths()
    if errors:
        for err in errors:
            sys.stderr.write(f"ERROR: {err}\n")
        return 1

    if not paths:
        return 0

    commit_tooling = [path for path in paths if _is_commit_tooling_path(path)]
    if not commit_tooling:
        return 0

    other = [path for path in paths if path not in commit_tooling]
    has_pre_commit_config = any(path.as_posix() == ".pre-commit-config.yaml" for path in commit_tooling)

    if has_pre_commit_config and len(paths) > 1:
        _emit_pre_commit_config_error(commit_tooling, other)
        return 1

    if other:
        _emit_mixed_tooling_error(commit_tooling, other)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
