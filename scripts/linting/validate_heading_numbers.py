#!/usr/bin/env python3
"""Validate and optionally fix numbered heading consistency in Markdown files.

This script checks that:
1. Section numbers are sequential (1, 2, 3, not 1, 3, 4)
2. Subsection numbers match their parent (## 5. Section → ### 5.1, 5.2, not 4.1)
3. Subsection numbers are sequential within their parent

Usage:
    python validate-heading-numbers.py [--fix] [files...]

Examples:
    python validate-heading-numbers.py docs/automation/runbooks/*.md
    python validate-heading-numbers.py --fix docs/automation/runbooks/phase-0-control-node-setup.md
"""

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import NamedTuple


class HeadingIssue(NamedTuple):
    """Represents a heading numbering issue."""

    line_num: int
    line: str
    expected: str
    actual: str
    issue_type: str


def _match_heading(line: str) -> tuple[int, str, str, str] | None:
    """Lightweight, non-backtracking heading matcher.

    Returns (level, number_str, title, hashes) or None if not a numbered heading.
    Enforces:
    - Leading hashes at start of line (## to ######)
    - At least one space after hashes
    - Number string of 1-6 dot-separated integer segments, optional trailing dot
    - Title present (non-empty)
    """
    if not line.startswith("#"):
        return None

    idx = 0
    while idx < len(line) and line[idx] == "#":
        idx += 1
    level = idx
    if level < 2 or level > 6:
        return None

    if idx >= len(line) or line[idx] not in (" ", "\t"):
        return None

    rest = line[idx:].lstrip(" \t")
    parts = rest.split(None, 1)
    if len(parts) < 2:
        return None
    number_str, title = parts

    trailing_dot = number_str.endswith(".")
    num_core = number_str[:-1] if trailing_dot else number_str
    segments = num_core.split(".")
    if not 1 <= len(segments) <= 6:
        return None
    if not all(seg.isdigit() for seg in segments):
        return None

    hashes = "#" * level
    return level, number_str, title, hashes


class _HeadingState:
    def __init__(self) -> None:
        self.current_parent: list[int] = []
        self.next_section_num = 1
        self.subsection_counters: dict[int, int] = {}

    def expected_for(self, level: int, actual_nums: list[int]) -> list[int]:
        if level == 2:
            return self._expected_for_section()
        return self._expected_for_subsection(level, actual_nums)

    def _expected_for_section(self) -> list[int]:
        expected_nums = [self.next_section_num]
        self.next_section_num += 1
        self.current_parent = expected_nums.copy()
        self.subsection_counters = {3: 1}
        return expected_nums

    def _expected_for_subsection(self, level: int, actual_nums: list[int]) -> list[int]:
        parent_prefix = self._parent_prefix(level, actual_nums)
        sub_num = self.subsection_counters.get(level, 1)
        expected_nums = [*parent_prefix, sub_num]

        self.subsection_counters[level] = sub_num + 1
        self._reset_deeper_counters(level)
        self.current_parent = expected_nums.copy()
        return expected_nums

    def _parent_prefix(self, level: int, actual_nums: list[int]) -> list[int]:
        parent_depth = level - 2
        if parent_depth <= len(self.current_parent):
            return self.current_parent[:parent_depth]
        if len(actual_nums) > 1:
            return actual_nums[:-1]
        return []

    def _reset_deeper_counters(self, level: int) -> None:
        for deeper_level in range(level + 1, 7):
            self.subsection_counters[deeper_level] = 1


def _issue_type(actual_nums: list[int], expected_nums: list[int]) -> str:
    if len(actual_nums) == 1:
        return "sequence"
    if len(actual_nums) > 1 and actual_nums[:-1] != expected_nums[:-1]:
        return "parent_mismatch"
    return "subsection_sequence"


def parse_heading_number(num_str: str) -> list[int]:
    """Parse '1.2.3' or '1.2.3.' into [1, 2, 3]."""
    clean = num_str.rstrip(".")
    return [int(part) for part in clean.split(".") if part]


def format_heading_number(nums: list[int], trailing_dot: bool = False) -> str:
    """Format [1, 2, 3] into '1.2.3' or '1.2.3.'."""
    result = ".".join(str(num) for num in nums)
    if trailing_dot:
        result += "."
    return result


def validate_file(filepath: Path, fix: bool = False) -> list[HeadingIssue]:
    """Validate heading numbers in a file. Optionally fix issues.

    Validates that:
    1. Top-level sections (##) are sequential: 1, 2, 3...
    2. Subsections match their parent: ## 5. → ### 5.1, 5.2, 5.3
    3. Subsection numbers reset when parent changes
    """
    issues: list[HeadingIssue] = []
    lines = filepath.read_text(encoding="utf-8").splitlines(keepends=True)

    state = _HeadingState()

    fixed_lines: list[str] = []

    for line_num, line in enumerate(lines, start=1):
        stripped = line.rstrip("\n\r")
        match = _match_heading(stripped)
        if not match:
            fixed_lines.append(line)
            continue

        level, num_str, title, hashes = match
        actual_nums = parse_heading_number(num_str)
        has_trailing_dot = num_str.endswith(".")

        expected_nums = state.expected_for(level, actual_nums)

        expected_str = format_heading_number(expected_nums, has_trailing_dot)
        actual_str = num_str

        if actual_nums != expected_nums:
            issues.append(
                HeadingIssue(
                    line_num=line_num,
                    line=line.rstrip(),
                    expected=expected_str,
                    actual=actual_str,
                    issue_type=_issue_type(actual_nums, expected_nums),
                )
            )
            # Fix the line
            fixed_line = f"{hashes} {expected_str} {title}"
            if line.endswith("\n"):
                fixed_line += "\n"
            fixed_lines.append(fixed_line)
        else:
            fixed_lines.append(line)

    if fix and issues:
        filepath.write_text("".join(fixed_lines), encoding="utf-8")
        print(f"Fixed {len(issues)} issues in {filepath}")

    return issues


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    if count == 1:
        return singular
    return plural or f"{singular}s"


def _summarize_issues(issues: list[HeadingIssue]) -> str:
    counts = Counter(issue.issue_type for issue in issues)
    parts: list[str] = []
    for key in ("sequence", "parent_mismatch", "subsection_sequence"):
        if key in counts:
            parts.append(f"{key}={counts[key]}")
    for key in sorted(counts.keys()):
        if key not in {"sequence", "parent_mismatch", "subsection_sequence"}:
            parts.append(f"{key}={counts[key]}")
    return ", ".join(parts) if parts else "(no issue types)"


class _RunResult(NamedTuple):
    checked_files: int
    total_issues: int
    total_error_files: int


def _iter_files(args_files: list[Path]) -> list[Path]:
    if args_files:
        return args_files
    docs_dir = Path("docs")
    if docs_dir.exists():
        return list(docs_dir.rglob("*.md"))
    return []


def _process_files(files: list[Path], fix: bool) -> _RunResult:
    checked_files = 0
    total_issues = 0
    total_error_files = 0

    for filepath in files:
        if not filepath.exists():
            print(f"WARNING: {filepath} does not exist, skipping")
            continue

        checked_files += 1
        try:
            issues = validate_file(filepath, fix=fix)
        except Exception as exc:
            total_error_files += 1
            print(f"ERROR: {filepath}: {type(exc).__name__}: {exc}")
            continue

        if not issues:
            continue

        total_issues += len(issues)

        if fix:
            continue

        print(f"\n{filepath}: {len(issues)} {_plural(len(issues), 'issue')}; {_summarize_issues(issues)}")
        for issue in issues:
            msg = f"L{issue.line_num}: {issue.issue_type}: expected '{issue.expected}', found '{issue.actual}'"
            print(f"  {msg}")
            print(f"    {issue.line}")

    return _RunResult(
        checked_files=checked_files,
        total_issues=total_issues,
        total_error_files=total_error_files,
    )


def main() -> int:
    """Main entry point."""
    desc = "Validate numbered heading consistency in Markdown files."
    parser = argparse.ArgumentParser(description=desc)
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Automatically fix heading number issues",
    )
    parser.add_argument(
        "files",
        nargs="*",
        type=Path,
        help="Markdown files to check (default: all .md in docs/)",
    )
    args = parser.parse_args()

    files = _iter_files(args.files)

    if not files:
        print("No markdown files found to check.")
        return 0

    result = _process_files(files, fix=args.fix)

    if result.total_error_files > 0:
        print(
            f"\nERROR: {result.total_error_files} {_plural(result.total_error_files, 'file')} could not be processed."
        )
        return 2

    if result.total_issues > 0 and not args.fix:
        print(
            f"\nFAIL: {result.total_issues} heading number {_plural(result.total_issues, 'issue')} across "
            f"{result.checked_files} {_plural(result.checked_files, 'file')}."
        )
        print("Run with --fix to automatically correct them.")
        return 1

    if args.fix:
        print(
            f"OK: checked {result.checked_files} {_plural(result.checked_files, 'file')}; "
            f"fixed {result.total_issues} heading number {_plural(result.total_issues, 'issue')}."
        )
        return 0

    print(f"OK: checked {result.checked_files} {_plural(result.checked_files, 'file')}; 0 heading number issues.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
