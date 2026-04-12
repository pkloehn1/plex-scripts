#!/usr/bin/env python3
"""Enforce repository layout invariants for Swarm stack files, env files, and secrets.

Rules:
-   Compose files must live only in:
    -   ``stacks/**/docker-compose.yml|yaml`` (Swarm stacks)
-   Swarm stack files must contain a services map and must NOT define ``name:``.
-   Block tracked env files except ``.env.template.swarm``.
-   Block tracked ``secrets/`` files (except ``.gitkeep``).
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import yaml

from scripts.testing.hooks.git_utils import get_staged_paths as _get_staged_paths
from scripts.testing.hooks.git_utils import read_staged_file as _read_staged_file


@dataclass
class Violation:
    path: Path
    reason: str


def _is_yaml_path(path: Path) -> bool:
    return path.suffix in {".yml", ".yaml"}


def _is_env_violation(path: Path) -> bool:
    name = path.name
    if name in {".env.template.swarm"}:
        return False
    if name == ".env" or name.startswith(".env."):
        return True
    return name.endswith(".env")


def _is_secret_violation(path: Path) -> bool:
    parts = path.parts
    if not parts:
        return False
    if parts[0] != "secrets":
        return False
    return path.name != ".gitkeep"


def _is_truenas_config(path: Path) -> bool:
    """TrueNAS container configs use compose-like YAML but are NOT Swarm stacks."""
    return len(path.parts) >= 2 and path.parts[:2] == ("app-config", "truenas")


def _is_allowed_compose_path(path: Path) -> bool:
    if path.parts == ():
        return False

    # TrueNAS configs are compose-like but not Swarm stacks - skip validation
    if _is_truenas_config(path):
        return True

    # Swarm stacks: stacks/<role>/docker-compose.yml (exactly 3 parts)
    return (
        len(path.parts) == 3
        and path.parts[0] == "stacks"
        and path.name
        in {
            "docker-compose.yml",
            "docker-compose.yaml",
        }
    )


class _PermissiveLoader(yaml.SafeLoader):
    """SafeLoader that treats unknown YAML tags (e.g., !secret) as scalars."""


_PermissiveLoader.add_multi_constructor(
    "",
    lambda loader, suffix, node: loader.construct_scalar(node),
)


def _parse_yaml_documents(raw: str) -> tuple[list[dict], str | None]:
    docs: list[dict] = []
    try:
        for doc in yaml.load_all(raw, Loader=_PermissiveLoader):
            if isinstance(doc, dict):
                docs.append(doc)
            else:
                docs.append({"__non_dict": True})
    except yaml.YAMLError as exc:
        return [], f"YAML parse error: {exc}"
    return docs, None


def _has_doc_markers(raw: str) -> bool:
    lines = [line_text.rstrip() for line_text in raw.splitlines()]
    non_empty = [line_text for line_text in lines if line_text.strip()]
    if not non_empty:
        return False
    return non_empty[0].startswith("---") and non_empty[-1] == "..."


def _is_compose_doc(doc: dict) -> bool:
    compose_keys = {"services", "include", "networks", "volumes", "secrets", "configs"}
    return any(key_name in doc for key_name in compose_keys)


def _validate_include_doc(path: Path, doc: dict) -> list[Violation]:
    violations: list[Violation] = []
    services = doc.get("services")
    if services is not None and not isinstance(services, dict):
        violations.append(
            Violation(
                path,
                "Compose services must be a mapping when present (include-only allowed)",
            )
        )

    if "name" in doc:
        violations.append(Violation(path, "Swarm stack compose files must NOT include name:"))

    return violations


def _validate_compose_doc(path: Path, doc: dict) -> list[Violation]:
    violations: list[Violation] = []

    if "include" in doc:
        return _validate_include_doc(path, doc)

    services = doc.get("services")
    if not isinstance(services, dict) or not services:
        violations.append(
            Violation(
                path,
                "Compose files must define services with at least one service entry",
            )
        )
        return violations

    if "name" in doc:
        violations.append(Violation(path, "Swarm stack compose files must NOT include name:"))

    return violations


def _validate_compose(path: Path, raw: str) -> list[Violation]:
    violations: list[Violation] = []
    docs, parse_error = _parse_yaml_documents(raw)
    if parse_error:
        return [Violation(path, parse_error)]

    compose_docs = [doc for doc in docs if _is_compose_doc(doc)]
    if not compose_docs:
        return violations

    if len(docs) != 1:
        return [
            Violation(
                path,
                "Compose YAML must contain exactly one document (no multi-doc files)",
            )
        ]

    if not _has_doc_markers(raw):
        violations.append(Violation(path, "Compose YAML must start with '---' and end with '...' markers"))

    if not _is_allowed_compose_path(path):
        violations.append(
            Violation(
                path,
                "Compose files must live in stacks/**/docker-compose.yml",
            )
        )
        return violations

    violations.extend(_validate_compose_doc(path, compose_docs[0]))
    return violations


def _collect_violations(paths: Iterable[Path]) -> list[Violation]:
    violations: list[Violation] = []
    for path in paths:
        if _is_env_violation(path):
            violations.append(
                Violation(
                    path,
                    "Tracked env files are blocked; use .env.template.swarm only",
                )
            )
            continue

        if _is_secret_violation(path):
            violations.append(
                Violation(
                    path,
                    "Tracked secrets are blocked; use Docker secrets or external storage instead",
                )
            )
            continue

        if not _is_yaml_path(path):
            continue

        raw, err = _read_staged_file(path)
        if err:
            violations.append(Violation(path, err))
            continue
        if raw is None:
            violations.append(Violation(path, "Unable to read staged file content"))
            continue

        violations.extend(_validate_compose(path, raw))

    return violations


def main() -> int:
    paths, errors = _get_staged_paths()
    if errors:
        for err in errors:
            sys.stderr.write(f"ERROR: {err}\n")
        return 1

    violations = _collect_violations(paths)
    if not violations:
        return 0

    sys.stderr.write("\nERROR: Repository layout invariants violated:\n")
    for violation in violations:
        sys.stderr.write(f"  - {violation.path}: {violation.reason}\n")
    sys.stderr.write(
        "\nAllowed compose locations:\n"
        "  - stacks/**/docker-compose.yml (Swarm stacks)\n\n"
        "Blocked files:\n"
        "  - .env / *.env (except .env.template.swarm)\n"
        "  - secrets/** (except .gitkeep)\n"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
