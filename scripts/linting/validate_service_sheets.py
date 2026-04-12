#!/usr/bin/env python3
"""Validate service inventory sheets match their template structure.

Each service sheet in docs/inventory/services/ must declare a template type
via an HTML comment (<!-- template: group --> or <!-- template: single -->).
This linter extracts the required H2 headings from the matching template
and verifies the service sheet contains them in the correct order.

Usage:
    python validate_service_sheets.py [files...]
    python validate_service_sheets.py  # scans docs/inventory/services/

Exit codes:
    0 = all checks passed
    1 = one or more sheets have structural issues
    2 = processing error (missing template, unreadable file)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import NamedTuple

_TEMPLATE_DIR = Path("docs/inventory/services")
_TEMPLATE_COMMENT_RE = re.compile(r"<!--\s*template:\s*(single|group)\s*-->")
_H2_RE = re.compile(r"^##\s+(.+)$")


class Finding(NamedTuple):
    """A single validation finding."""

    file: Path
    message: str


def _extract_h2_headings(text: str) -> list[str]:
    """Return ordered list of H2 heading text from markdown content."""
    headings: list[str] = []
    for line in text.splitlines():
        match = _H2_RE.match(line.strip())
        if match:
            headings.append(match.group(1).strip())
    return headings


def _detect_template_type(text: str) -> str | None:
    """Return 'single' or 'group' from the template comment, or None."""
    match = _TEMPLATE_COMMENT_RE.search(text)
    if match:
        return match.group(1)
    return None


def _load_template(template_type: str, repo_root: Path) -> list[str] | None:
    """Load and return H2 headings from the matching template file."""
    template_path = repo_root / _TEMPLATE_DIR / f"_template-{template_type}.md"
    if not template_path.exists():
        return None
    text = template_path.read_text(encoding="utf-8")
    return _extract_h2_headings(text)


def validate_sheet(filepath: Path, repo_root: Path) -> list[Finding]:
    """Validate a single service sheet against its template."""
    findings: list[Finding] = []

    text = filepath.read_text(encoding="utf-8")

    template_type = _detect_template_type(text)
    if template_type is None:
        findings.append(
            Finding(
                file=filepath,
                message="Missing template declaration (<!-- template: single --> or <!-- template: group -->).",
            )
        )
        return findings

    template_headings = _load_template(template_type, repo_root)
    if template_headings is None:
        findings.append(
            Finding(
                file=filepath,
                message=f"Template file _template-{template_type}.md not found.",
            )
        )
        return findings

    sheet_headings = _extract_h2_headings(text)

    # Check for missing required sections.
    for heading in template_headings:
        if heading not in sheet_headings:
            findings.append(
                Finding(
                    file=filepath,
                    message=f"Missing required section: ## {heading} (template: {template_type})",
                )
            )

    # Check for extra sections not in template.
    for heading in sheet_headings:
        if heading not in template_headings:
            findings.append(
                Finding(
                    file=filepath,
                    message=f"Extra section not in template: ## {heading} (template: {template_type})",
                )
            )

    # Check ordering of sections that are present in both.
    common_in_template = [hdg for hdg in template_headings if hdg in sheet_headings]
    common_in_sheet = [hdg for hdg in sheet_headings if hdg in template_headings]
    if common_in_template != common_in_sheet:
        findings.append(
            Finding(
                file=filepath,
                message=f"Section order does not match template ({template_type}). Expected: {common_in_template}",
            )
        )

    return findings


def _find_repo_root() -> Path:
    """Walk up from cwd to find the repo root (contains .git)."""
    candidate = Path.cwd()
    while candidate != candidate.parent:
        if (candidate / ".git").exists():
            return candidate
        candidate = candidate.parent
    return Path.cwd()


def _iter_service_sheets(repo_root: Path) -> list[Path]:
    """Return all non-template .md files in the services directory."""
    services_dir = repo_root / _TEMPLATE_DIR
    if not services_dir.exists():
        return []
    return [path for path in sorted(services_dir.glob("*.md")) if not path.name.startswith("_")]


class _RunResult(NamedTuple):
    all_findings: list[Finding]
    error_files: int


def _process_files(files: list[Path], repo_root: Path) -> _RunResult:
    """Validate each file, collecting findings and error counts."""
    all_findings: list[Finding] = []
    error_files = 0

    for filepath in files:
        if not filepath.exists():
            print(f"WARNING: {filepath} does not exist, skipping")
            continue

        try:
            findings = validate_sheet(filepath, repo_root)
            all_findings.extend(findings)
        except Exception as exc:
            error_files += 1
            print(f"ERROR: {filepath}: {type(exc).__name__}: {exc}")

    return _RunResult(all_findings=all_findings, error_files=error_files)


def _print_findings(findings: list[Finding], repo_root: Path) -> None:
    """Print each finding with a repo-relative path."""
    for finding in findings:
        try:
            rel = finding.file.relative_to(repo_root)
        except ValueError:
            rel = finding.file
        print(f"{rel}: {finding.message}")


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Validate service inventory sheets match their template structure.",
    )
    parser.add_argument(
        "files",
        nargs="*",
        type=Path,
        help="Service sheet files to check (default: all in docs/inventory/services/)",
    )
    args = parser.parse_args()

    repo_root = _find_repo_root()

    files = args.files if args.files else _iter_service_sheets(repo_root)
    if not files:
        return 0

    result = _process_files(files, repo_root)

    if result.error_files > 0:
        return 2

    if not result.all_findings:
        file_count = len(files)
        label = "file" if file_count == 1 else "files"
        print(f"OK: {file_count} service {label} validated against templates.")
        return 0

    _print_findings(result.all_findings, repo_root)
    print(f"\nFAIL: {len(result.all_findings)} issue(s) found.")
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
