#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_CHECK_ID = "COMPOSE-NETWORK-001"


@dataclass(frozen=True)
class Finding:
    path: Path
    service: str
    message: str


def check_compose_network_mode_conflicts(compose: dict[str, Any], file_path: Path) -> list[Finding]:
    services = compose.get("services")
    if not isinstance(services, dict):
        return []

    findings: list[Finding] = []
    for service_name, service_config in services.items():
        if not isinstance(service_config, dict):
            continue

        if "network_mode" in service_config and "networks" in service_config:
            findings.append(
                Finding(
                    path=file_path,
                    service=str(service_name),
                    message=(
                        f"{_CHECK_ID}: services may not define both 'network_mode' and 'networks'. "
                        "Remove one of the keys to match Docker Compose semantics."
                    ),
                )
            )

    return findings


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate Docker Compose files for incompatible networking options. "
            "Specifically, reject services that define both network_mode and networks."
        )
    )
    parser.add_argument("files", nargs="+", type=Path, help="Compose YAML file(s) to check")
    return parser.parse_args(argv)


def _load_yaml(file_path: Path) -> dict[str, Any] | None:
    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        sys.stderr.write(f"{file_path}: FILE-READ-001: Failed to read file: {exc}\n")
        return None

    try:
        loaded = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        sys.stderr.write(f"{file_path}: YAML-PARSE-001: Failed to parse YAML: {exc}\n")
        return None

    if not isinstance(loaded, dict):
        return {}

    return loaded


def main(argv: list[str]) -> int:
    args = _parse_args(argv)

    any_errors = False
    for file_path in args.files:
        compose = _load_yaml(file_path)
        if compose is None:
            any_errors = True
            continue

        findings = check_compose_network_mode_conflicts(compose, file_path=file_path)
        for finding in findings:
            any_errors = True
            sys.stderr.write(f"{finding.path}: {finding.service}: {finding.message}\n")

    return 1 if any_errors else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
