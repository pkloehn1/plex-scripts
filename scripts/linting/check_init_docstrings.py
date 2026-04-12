#!/usr/bin/env python3
"""Check that all __init__.py files have proper module docstrings.

Per Python Style Guide:
- All package __init__.py files MUST have a module docstring
- Test package docstrings should follow: 'Tests for <package>.'
- Domain package docstrings should briefly describe the package purpose
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Finding:
    path: Path
    message: str


def _repo_root() -> Path:
    """Get repository root by walking up to find pyproject.toml."""
    from scripts.common.paths import repo_root

    return repo_root()


def _get_docstring(source: str) -> str | None:
    """Extract module docstring from Python source."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    return ast.get_docstring(tree)


def _is_test_package(init_path: Path) -> bool:
    """Check if __init__.py is in a test package."""
    return init_path.parent.name in {"tests", "test"}


def _check_init_file(init_path: Path) -> Finding | None:
    """Check a single __init__.py file for proper docstring."""
    if not init_path.exists():
        return Finding(init_path, "File does not exist")

    source = init_path.read_text(encoding="utf-8")

    # Check for single-line comment instead of docstring
    first_line = source.strip().split("\n")[0] if source.strip() else ""
    if first_line.startswith("#"):
        return Finding(
            init_path,
            f"Has comment instead of docstring: {first_line[:50]}",
        )

    docstring = _get_docstring(source)

    if docstring is None:
        return Finding(init_path, "Missing module docstring")

    # Validate test package docstring format
    if _is_test_package(init_path):
        expected_prefix = "Tests for "
        if not docstring.startswith(expected_prefix):
            return Finding(
                init_path,
                f"Test package docstring should start with '{expected_prefix}'",
            )

    return None


def find_violations() -> list[Finding]:
    """Find all __init__.py files with missing or improper docstrings."""
    repo_root = _repo_root()
    scripts_dir = repo_root / "scripts"

    if not scripts_dir.exists():
        return [Finding(scripts_dir, "scripts/ directory not found")]

    findings: list[Finding] = []

    for init_file in scripts_dir.rglob("__init__.py"):
        if finding := _check_init_file(init_file):
            findings.append(finding)

    return sorted(findings, key=lambda finding: str(finding.path))


def main() -> int:
    """Check all __init__.py files and report violations."""
    findings = find_violations()

    if not findings:
        print("PASS: all __init__.py files have proper docstrings")
        return 0

    print("Findings:")
    for finding in findings:
        print(f"- {finding.path.relative_to(_repo_root())}: {finding.message}")

    print(f"\nFAIL: {len(findings)} __init__.py file(s) missing proper docstrings")
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
