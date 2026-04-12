#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Violation:
    code: str
    path: Path
    message: str
    line: int | None = None


_WORKFLOW_FILE_PATTERN = re.compile(r"\.ya?ml$", re.IGNORECASE)

_GITHUB_DIR_NAME = ".github"

_FOLLOW_UP_ISSUES = (
    "Issue #18: Add C1 validator (enforce `concurrency:` policy for PR workflows).",
    "Issue #19: Add C3 validator (require `actions/checkout@v4` where repo content is needed).",
    "Issue #21: Add C4 validator (ban `curl|bash` / `wget|bash` pipe-to-shell patterns).",
)

# Notes:
# - Keep parity with `kloehnwars-homelab` architecture validators by using text-based checks.
# - Avoid YAML parsers here because YAML 1.1 boolean coercion can treat `on` as `True`.

# PERM001: Require explicit top-level permissions (accepts empty mapping `{}`).
_PERMISSIONS_AT_ROOT = re.compile(r"^permissions:\s*(\{\}|#.*)?$", re.MULTILINE)

# PERM002: Every job must declare its own `permissions:` block.
_JOBS_LINE = re.compile(r"^jobs:\s*(#.*)?$", re.MULTILINE)
_JOB_DEF = re.compile(r"^ {2}(\w[\w-]*):\s*(#.*)?$", re.MULTILINE)
_JOB_PERMISSIONS = re.compile(r"^ {4}permissions:\s*", re.MULTILINE)

# PIN001/PIN002 (simplified): Require `uses:` actions pinned to MAJOR-only tags (`@vN`).
# Allow local actions (`./...`) and docker images (`docker://...`).
_USES_LINE = re.compile(r"^\s*(?:-\s*)?uses:\s*(?P<target>[^\s#]+)", re.MULTILINE)
_PINNED_MAJOR = re.compile(r"@v\d+$")

# ORCH001: Orchestrator workflows must contain `uses:` only (no `run:` or `shell:`).
_FORBIDDEN_ORCH = re.compile(r"^\s*(?:-\s*)?(run|shell):\s+", re.MULTILINE)

# REUSE001: Reusable workflows must define `on: workflow_call`.
_WORKFLOW_CALL = re.compile(r"^\s*workflow_call\s*:\s*(#.*)?$", re.MULTILINE)

# SYNC001: `sync-labels: true` causes label flapping when multiple jobs manage labels.
_SYNC_LABELS_TRUE = re.compile(r"^\s*sync-labels:\s*true\b", re.MULTILINE)


def _repo_root(explicit_root: str | None) -> Path:
    if explicit_root:
        return Path(explicit_root).resolve()

    from scripts.common.paths import repo_root

    return repo_root()


def _iter_workflow_files(workflows_dir: Path) -> list[Path]:
    if not workflows_dir.exists():
        return []

    return sorted(
        path for path in workflows_dir.rglob("*") if path.is_file() and _WORKFLOW_FILE_PATTERN.search(path.name)
    )


def _line_number_for_match(text: str, match_start: int) -> int:
    return text.count("\n", 0, match_start) + 1


def validate_permissions_present(path: Path, text: str) -> list[Violation]:
    if _PERMISSIONS_AT_ROOT.search(text):
        return []
    return [
        Violation(
            code="PERM001",
            path=path,
            message="Missing top-level `permissions:` block",
            line=None,
        )
    ]


def validate_job_permissions(path: Path, text: str) -> list[Violation]:
    """PERM002: Every job must declare its own ``permissions:`` block."""
    jobs_match = _JOBS_LINE.search(text)
    if not jobs_match:
        return []

    violations: list[Violation] = []

    for job_match in _JOB_DEF.finditer(text, jobs_match.end()):
        job_name = job_match.group(1)
        job_start = job_match.end()

        # Find the end of this job block (next job definition or end of text).
        next_job = _JOB_DEF.search(text, job_start)
        job_end = next_job.start() if next_job else len(text)
        job_block = text[job_start:job_end]

        if not _JOB_PERMISSIONS.search(job_block):
            violations.append(
                Violation(
                    code="PERM002",
                    path=path,
                    message=f"Job `{job_name}` missing `permissions:` block",
                    line=_line_number_for_match(text, job_match.start()),
                )
            )

    return violations


def validate_action_pinning(path: Path, text: str) -> list[Violation]:
    violations: list[Violation] = []

    for match in _USES_LINE.finditer(text):
        target = match.group("target")

        if target.startswith("./"):
            continue
        if target.startswith("docker://"):
            continue

        # Example: actions/checkout@v4, docker/login-action@v3
        if "@" not in target:
            violations.append(
                Violation(
                    code="PIN001",
                    path=path,
                    message=f"Unpinned action reference: `{target}` (missing `@vN`)",
                    line=_line_number_for_match(text, match.start()),
                )
            )
            continue

        ref = target.rsplit("@", 1)[1]
        if not _PINNED_MAJOR.fullmatch(f"@{ref}"):
            violations.append(
                Violation(
                    code="PIN002",
                    path=path,
                    message=(f"Action pin must be MAJOR-only `@vN`: `{target}` (found `@{ref}`)"),
                    line=_line_number_for_match(text, match.start()),
                )
            )

    return violations


def validate_orchestrator_purity(path: Path, text: str) -> list[Violation]:
    match = _FORBIDDEN_ORCH.search(text)
    if not match:
        return []

    return [
        Violation(
            code="ORCH001",
            path=path,
            message="Orchestrator workflows must not use `run:` or `shell:`",
            line=_line_number_for_match(text, match.start()),
        )
    ]


def validate_reusable_workflow_call(path: Path, text: str) -> list[Violation]:
    if _WORKFLOW_CALL.search(text):
        return []

    return [
        Violation(
            code="REUSE001",
            path=path,
            message="Reusable workflows must include `on: workflow_call`",
            line=None,
        )
    ]


def validate_no_sync_labels(path: Path, text: str) -> list[Violation]:
    match = _SYNC_LABELS_TRUE.search(text)
    if not match:
        return []

    return [
        Violation(
            code="SYNC001",
            path=path,
            message="Labeler `sync-labels: true` causes flapping when multiple jobs manage labels",
            line=_line_number_for_match(text, match.start()),
        )
    ]


def validate_root_workflow_not_workflow_call_only(path: Path, text: str) -> list[Violation]:
    if not _WORKFLOW_CALL.search(text):
        return []

    return [
        Violation(
            code="PLACE002",
            path=path,
            message="Root workflows in `.github/workflows/` must not be reusable-only (`workflow_call`)",
            line=None,
        )
    ]


def validate_repo(root: Path) -> list[Violation]:
    workflows_dir = root / _GITHUB_DIR_NAME / "workflows"

    violations: list[Violation] = []

    # Workflow files: `.github/workflows/**` (including subdirectories).
    for path in _iter_workflow_files(workflows_dir):
        rel = path.relative_to(root)
        text = path.read_text(encoding="utf-8")

        is_root_workflow = rel.parent == Path(f"{_GITHUB_DIR_NAME}/workflows")
        is_orchestrator = rel.parts[:3] == (
            _GITHUB_DIR_NAME,
            "workflows",
            "orchestrators",
        )
        is_reusable = rel.parts[:3] == (_GITHUB_DIR_NAME, "workflows", "reusable")

        violations.extend(validate_permissions_present(rel, text))
        violations.extend(validate_job_permissions(rel, text))
        violations.extend(validate_action_pinning(rel, text))
        violations.extend(validate_no_sync_labels(rel, text))

        if is_root_workflow:
            violations.extend(validate_root_workflow_not_workflow_call_only(rel, text))

        if is_orchestrator:
            violations.extend(validate_orchestrator_purity(rel, text))

        if is_reusable:
            violations.extend(validate_reusable_workflow_call(rel, text))

    return violations


def _format_violation(violation: Violation) -> str:
    if violation.line is None:
        return f"{violation.code}: {violation.path}: {violation.message}"
    return f"{violation.code}: {violation.path}:{violation.line}: {violation.message}"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate GitHub Actions workflow architecture invariants (pinning, permissions, placement/purity)."
        )
    )
    parser.add_argument("--root", help="Repository root (defaults to git root)")

    args = parser.parse_args(argv)
    root = _repo_root(args.root)

    violations = validate_repo(root)
    if not violations:
        return 0

    print("GitHub Actions architecture validation failed:\n")
    for violation in violations:
        print(f"- {_format_violation(violation)}")

    print("\nRemediation (see docs/repository-standards/style-guides/github-actions-style-guide.md):")
    print("- Add `permissions: {}` at workflow level (zero-trust default)")
    print("- Add explicit `permissions:` on every job (job-level grants)")
    print("- Pin `uses:` actions to MAJOR-only tags like `@v6` (not branches or SHAs)")
    print(
        "- Keep reusable workflows under `.github/workflows/reusable/` and orchestrators under `.github/workflows/orchestrators/`"
    )

    print("\nFollow-up invariants (tracked issues):")
    for item in _FOLLOW_UP_ISSUES:
        print(f"- {item}")

    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
