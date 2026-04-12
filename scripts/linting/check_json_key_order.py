#!/usr/bin/env python3
"""Check that JSON files have alphabetically sorted keys.

Validates top-level and nested object keys are in case-insensitive
alphabetical order.  Array element ordering is not enforced.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Finding:
    path: Path
    message: str


def _sorted_key(key: str) -> str:
    """Return a case-insensitive sort key."""
    return key.casefold()


def _build_violation_message(
    json_path: str,
    keys: list[str],
    idx: int,
    actual: str,
    expected: str,
) -> str:
    """Build a human-readable message for a key ordering violation."""
    if idx == 0:
        return f"{json_path}: key {actual!r} at position {idx} should be first — expected {expected!r}"
    return f"{json_path}: key {actual!r} at position {idx} should come after {keys[idx - 1]!r} — expected {expected!r}"


def _find_dict_key_violation(
    keys: list[str],
    path: Path,
    json_path: str,
) -> Finding | None:
    """Return a Finding for the first out-of-order key, or None."""
    sorted_keys = sorted(keys, key=_sorted_key)
    for idx, (actual, expected) in enumerate(zip(keys, sorted_keys, strict=True)):
        if actual != expected:
            message = _build_violation_message(
                json_path,
                keys,
                idx,
                actual,
                expected,
            )
            return Finding(path, message)
    return None


def _check_object_keys(
    obj: object,
    path: Path,
    *,
    json_path: str = "$",
) -> list[Finding]:
    """Recursively check that all object keys are alphabetically sorted."""
    findings: list[Finding] = []

    if isinstance(obj, dict):
        violation = _find_dict_key_violation(list(obj.keys()), path, json_path)
        if violation:
            findings.append(violation)

        for key, value in obj.items():
            findings.extend(
                _check_object_keys(value, path, json_path=f"{json_path}.{key}"),
            )

    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            findings.extend(
                _check_object_keys(item, path, json_path=f"{json_path}[{idx}]"),
            )

    return findings


def check_file(file_path: Path) -> list[Finding]:
    """Check a single JSON file for key ordering violations."""
    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [Finding(file_path, f"Cannot read file: {exc}")]

    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        return [Finding(file_path, f"Invalid JSON: {exc}")]

    if not isinstance(data, (dict, list)):
        return []

    return _check_object_keys(data, file_path)


def main(argv: list[str] | None = None) -> int:
    """Check JSON files passed as arguments."""
    files = argv if argv is not None else sys.argv[1:]

    if not files:
        print("Usage: check_json_key_order.py <file> [file ...]")
        return 0

    all_findings: list[Finding] = []
    for file_arg in files:
        file_path = Path(file_arg)
        all_findings.extend(check_file(file_path))

    if not all_findings:
        print(f"PASS: {len(files)} JSON file(s) have sorted keys")
        return 0

    print("Findings:")
    for finding in all_findings:
        print(f"- {finding.path}: {finding.message}")

    print(f"\nFAIL: {len(all_findings)} key ordering violation(s)")
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
