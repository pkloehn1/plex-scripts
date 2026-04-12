#!/usr/bin/env python3

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    message: str


# Match common "test" usages that should be written with [[ ... ]] in bash.
# This is intentionally narrow (high-signal) to avoid false positives.
_DISALLOWED_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\b(if|elif|while|until)\s+\[\s+"),
        "Use [[ ... ]] instead of [ ... ] in bash conditionals.",
    ),
    (
        re.compile(r"\$\(\s*\[\s+"),
        "Use [[ ... ]] instead of [ ... ] inside command substitutions.",
    ),
    (
        re.compile(r"\$\(\s*test\s+"),
        "Use [[ ... ]] instead of test inside command substitutions.",
    ),
    (
        re.compile(r"(?:^|\s)(?:&&|\|\|)\s*\[\s+"),
        "Use [[ ... ]] instead of [ ... ] in bash conditionals.",
    ),
)


def _is_bash_script(path: Path) -> bool:
    if path.suffix != ".sh":
        return False

    try:
        first_line = path.read_text(encoding="utf-8", errors="replace").splitlines()[0]
    except IndexError:
        return True

    if first_line.startswith("#!"):
        return "bash" in first_line

    # Repo convention: .sh files are bash unless explicitly declared otherwise.
    return True


def find_disallowed_test_syntax(path: Path) -> list[Finding]:
    if not _is_bash_script(path):
        return []

    text = path.read_text(encoding="utf-8", errors="replace")

    findings: list[Finding] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue

        for pattern, message in _DISALLOWED_PATTERNS:
            if pattern.search(line):
                findings.append(Finding(path=path, line=idx, message=message))
                break

    return findings


def _iter_paths_from_argv(argv: list[str]) -> list[Path]:
    if len(argv) <= 1:
        # Safe default for manual runs.
        return sorted(Path.cwd().rglob("*.sh"))
    return [Path(arg) for arg in argv[1:]]


def main(argv: list[str]) -> int:
    paths = _iter_paths_from_argv(argv)

    all_findings: list[Finding] = []
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        all_findings.extend(find_disallowed_test_syntax(path))

    if not all_findings:
        return 0

    for finding in all_findings:
        rel = finding.path.resolve().relative_to(Path.cwd().resolve())
        sys.stderr.write(f"{rel}:{finding.line}: {finding.message}\n")

    sys.stderr.write("\nFix: replace [ ... ] with [[ ... ]] (bash scripts only).\n")
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv))
