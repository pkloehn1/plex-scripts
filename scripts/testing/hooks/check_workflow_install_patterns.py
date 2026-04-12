#!/usr/bin/env python3
"""Enforce GitHub Actions workflow invariants.

- Require actions/checkout in every job that has run steps.
- Forbid curl|bash and wget|sh style installs in run steps.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from pathlib import Path

import yaml

from scripts.testing.hooks.git_utils import get_staged_paths
from scripts.testing.hooks.git_utils import read_staged_file as _read_staged_file


def _get_staged_workflows() -> tuple[list[Path], list[str]]:
    paths, errors = get_staged_paths(".github/workflows/")
    yaml_paths = [path for path in paths if path.suffix in (".yml", ".yaml")]
    return yaml_paths, errors


def _parse_workflow(raw: str) -> tuple[list[dict], str | None]:
    docs: list[dict] = []
    try:
        for doc in yaml.safe_load_all(raw):
            if isinstance(doc, dict):
                docs.append(doc)
    except yaml.YAMLError as exc:  # pragma: no cover
        return [], f"YAML parse error: {exc}"
    return docs, None


def _job_has_checkout(job: dict) -> bool:
    steps = job.get("steps") or []
    return any(isinstance(step, dict) and str(step.get("uses", "")).startswith("actions/checkout") for step in steps)


def _run_step_strings(job: dict) -> Iterable[str]:
    for step in job.get("steps") or []:
        if isinstance(step, dict) and "run" in step:
            run_val = step.get("run")
            if isinstance(run_val, str):
                yield run_val


def _is_shell_token(token: str) -> bool:
    return token in {"bash", "sh"} or token.endswith("/bash") or token.endswith("/sh")


def _segment_contains_shell(segment: str) -> bool:
    token = ""
    for char in segment:
        if char.isspace():
            if _is_shell_token(token):
                return True
            token = ""
            continue

        if char.isalnum() or char in "/._-":
            if len(token) < 64:  # bound to avoid pathological growth
                token += char
            continue

        if _is_shell_token(token):
            return True
        token = ""

    return _is_shell_token(token)


def _contains_curl_bash(run_text: str) -> bool:
    lowered = run_text.lower()
    if "|" not in lowered or ("curl" not in lowered and "wget" not in lowered):
        return False

    return any(_segment_contains_shell(segment) for segment in lowered.split("|")[1:])


def _collect_violations(doc: dict) -> list[str]:
    violations: list[str] = []
    jobs = doc.get("jobs")
    if not isinstance(jobs, dict):
        return violations

    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps") or []
        has_checkout = _job_has_checkout(job)
        uses_only_api = all(isinstance(step, dict) and "run" not in step for step in steps)

        if not has_checkout and not uses_only_api:
            violations.append(f"Job '{job_id}' is missing actions/checkout")

        for run_text in _run_step_strings(job):
            if _contains_curl_bash(run_text):
                violations.append(f"Job '{job_id}' contains curl|bash or wget|sh pattern in a run step")

    return violations


def _violations_for_path(path: Path) -> list[tuple[Path, str]]:
    issues: list[tuple[Path, str]] = []
    raw, err = _read_staged_file(path)
    if err:
        issues.append((path, err))
        return issues
    if raw is None:
        issues.append((path, "Unable to read staged file content"))
        return issues

    docs, parse_err = _parse_workflow(raw)
    if parse_err is not None:
        issues.append((path, parse_err))
        return issues

    for doc in docs:
        for issue in _collect_violations(doc):
            issues.append((path, issue))
    return issues


def main() -> int:
    paths, errors = _get_staged_workflows()
    if errors:
        for err in errors:
            sys.stderr.write(f"ERROR: {err}\n")
        return 1

    violations: list[tuple[Path, str]] = []
    for path in paths:
        violations.extend(_violations_for_path(path))

    if not violations:
        return 0

    sys.stderr.write("\nERROR: Workflow invariants violated:\n")
    for path, issue in violations:
        sys.stderr.write(f"  - {path}: {issue}\n")
    sys.stderr.write(
        "\nRequirements:\n"
        "- Every job must include actions/checkout\n"
        "- curl|bash and wget|sh install patterns are forbidden in run steps\n"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
