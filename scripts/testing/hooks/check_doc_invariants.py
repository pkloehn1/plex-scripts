#!/usr/bin/env python3
"""Enforce documentation invariants for runbooks and architecture docs.

Rules:
-   Runbooks (``docs/automation/runbooks/*.md``):
    -   Must start with a top-level ``# `` heading.
    -   Must include numbered headings starting with ``## 1.`` and ``## 2.``.
-   Architecture docs (``docs/architecture/*.md``):
    -   Must start with a top-level ``# `` heading.
    -   Must include at least one ``## `` subsection heading.

Only staged files in those paths are checked.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from pathlib import Path

from scripts.testing.hooks.git_utils import get_staged_paths as _get_staged_paths
from scripts.testing.hooks.git_utils import read_staged_file


def _read_staged_file(path: Path) -> tuple[list[str] | None, str | None]:
    raw, err = read_staged_file(path)
    if err:
        return None, err
    if raw is None:
        return None, None
    return raw.splitlines(), None


def _is_runbook(path: Path) -> bool:
    parts = path.parts
    return (
        len(parts) >= 3
        and parts[0] == "docs"
        and parts[1] == "automation"
        and parts[2] == "runbooks"
        and path.suffix == ".md"
    )


def _is_architecture_doc(path: Path) -> bool:
    parts = path.parts
    return len(parts) >= 2 and parts[0] == "docs" and parts[1] == "architecture" and path.suffix == ".md"


def _has_top_heading(lines: list[str]) -> bool:
    for line in lines:
        if not line.strip():
            continue
        return line.startswith("# ")
    return False


def _has_numbered_headings(lines: list[str], numbers: Iterable[int]) -> bool:
    targets = {f"## {num}." for num in numbers}
    found = set()
    for line in lines:
        for target in targets:
            if line.startswith(target):
                found.add(target)
    return targets <= found


def _has_subheading(lines: list[str]) -> bool:
    return any(line.startswith("## ") for line in lines)


def _validate_runbook(lines: list[str]) -> list[str]:
    issues: list[str] = []
    if not _has_top_heading(lines):
        issues.append("Runbook must start with a top-level '# ' heading")
    if not _has_numbered_headings(lines, [1, 2]):
        issues.append("Runbook must include numbered sections starting with '## 1.' and '## 2.'")
    return issues


def _validate_architecture_doc(lines: list[str]) -> list[str]:
    issues: list[str] = []
    if not _has_top_heading(lines):
        issues.append("Architecture doc must start with a top-level '# ' heading")
    if not _has_subheading(lines):
        issues.append("Architecture doc must include at least one '## ' subsection heading")
    return issues


def _collect_violations(path: Path, lines: list[str]) -> list[str]:
    if _is_runbook(path):
        return _validate_runbook(lines)
    if _is_architecture_doc(path):
        return _validate_architecture_doc(lines)
    return []


def main() -> int:
    paths, errors = _get_staged_paths()
    if errors:
        for error_msg in errors:
            sys.stderr.write(f"ERROR: {error_msg}\n")
        return 1

    violations: list[tuple[Path, str]] = []
    for path in paths:
        if not (_is_runbook(path) or _is_architecture_doc(path)):
            continue
        lines, err = _read_staged_file(path)
        if err:
            violations.append((path, err))
            continue
        if lines is None:
            violations.append((path, "Unable to read staged file content"))
            continue

        for issue in _collect_violations(path, lines):
            violations.append((path, issue))

    if not violations:
        return 0

    sys.stderr.write("\nERROR: Documentation invariants violated:\n")
    for path, issue in violations:
        sys.stderr.write(f"  - {path}: {issue}\n")
    sys.stderr.write(
        "\nRunbooks (docs/automation/runbooks/*.md):\n"
        "  - Top-level '# ' heading required\n"
        "  - Numbered sections starting with '## 1.' and '## 2.' required\n"
        "\nArchitecture docs (docs/architecture/*.md):\n"
        "  - Top-level '# ' heading required\n"
        "  - At least one '## ' subsection required\n"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
