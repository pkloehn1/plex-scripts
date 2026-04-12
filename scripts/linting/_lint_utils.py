"""Shared types, helpers, and CLI scaffold for Docker Compose linters.

Both ``lint_swarm.py`` (Swarm stack validation) and ``lint_compose.py``
(non-Swarm Compose validation) share the severity model, result dataclass,
formatting, and CLI entry-point logic.  Keeping them here avoids duplication.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Shared types
# ---------------------------------------------------------------------------


class Severity(Enum):
    """Severity levels for lint results."""

    ERROR = "ERROR"  # Blocks deployment, must fix
    WARN = "WARN"  # Deprecated or ignored in Swarm, should fix
    INFO = "INFO"  # Suggestion for improvement


@dataclass
class LintResult:
    """Result of a lint check."""

    severity: Severity
    check_id: str
    service: str
    message: str
    file_path: str = ""
    line_num: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def tag_file_path(results: list[LintResult], file_path: Path) -> None:
    """Stamp every result in *results* with *file_path*."""
    for result in results:
        result.file_path = str(file_path)


def run_check(
    *,
    file_path: Path,
    compose: dict[str, Any],
    check: Callable[[dict[str, Any]], list[LintResult]],
) -> list[LintResult]:
    """Execute a single check function and tag results with the source file."""
    results = check(compose)
    tag_file_path(results, file_path)
    return results


def format_result(result: LintResult) -> str:
    """Format a lint result for CLI output."""
    location = f"{result.file_path}"
    if result.service:
        location += f" [{result.service}]"

    return f"{result.severity.value}: [{result.check_id}] {location}: {result.message}"


# ---------------------------------------------------------------------------
# CLI scaffold
# ---------------------------------------------------------------------------

_SEVERITY_ORDER: dict[Severity, int] = {
    Severity.ERROR: 0,
    Severity.WARN: 1,
    Severity.INFO: 2,
}


def cli_main(
    *,
    description: str,
    epilog: str,
    lint_fn: Callable[[Path], list[LintResult]],
) -> int:
    """Shared CLI entry point for linter scripts.

    Parameters
    ----------
    description:
        One-line description shown in ``--help``.
    epilog:
        Extended help text (exit codes, examples).
    lint_fn:
        A callable that accepts a :class:`~pathlib.Path` and returns lint results.
    """
    parser = argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=epilog,
    )
    parser.add_argument(
        "files",
        nargs="+",
        type=Path,
        help="Docker Compose files to lint",
    )
    parser.add_argument(
        "--severity",
        choices=["ERROR", "WARN", "INFO"],
        default="INFO",
        help="Minimum severity level to report (default: INFO)",
    )
    args = parser.parse_args()

    min_severity = Severity[args.severity]

    all_results: list[LintResult] = []
    has_missing_files = False
    for file_path in args.files:
        if not file_path.exists():
            print(f"ERROR: File not found: {file_path}", file=sys.stderr)
            has_missing_files = True
            continue
        results = lint_fn(file_path)
        all_results.extend(results)

    max_order = _SEVERITY_ORDER[min_severity]
    filtered = [result_item for result_item in all_results if _SEVERITY_ORDER[result_item.severity] <= max_order]
    filtered.sort(key=lambda result_item: _SEVERITY_ORDER[result_item.severity])

    for result in filtered:
        print(format_result(result))

    error_count = sum(1 for result_item in filtered if result_item.severity == Severity.ERROR)
    warn_count = sum(1 for result_item in filtered if result_item.severity == Severity.WARN)
    info_count = sum(1 for result_item in filtered if result_item.severity == Severity.INFO)

    if filtered:
        print(f"\nFound: {error_count} ERROR(s), {warn_count} WARN(s), {info_count} INFO(s)")
    else:
        print("All checks passed")

    return 1 if error_count > 0 or has_missing_files else 0
