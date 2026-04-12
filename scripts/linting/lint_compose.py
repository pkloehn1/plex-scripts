#!/usr/bin/env python3
"""Lint Docker Compose files for Traefik Compose compatibility.

Validates Docker Compose files that run Traefik with the Docker provider.
This is separate from Swarm stack linting to keep the rulesets isolated.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

from scripts.linting._lint_utils import (
    LintResult,
    Severity,
    cli_main,
)
from scripts.linting._lint_utils import (
    run_check as _run_check,
)
from scripts.linting.lint_swarm import (
    _HARDENING_ALLOW_ROOT_SERVICES,
    _as_string_list,
    _cap_drop_includes_all,
    _is_traefik_service,
    _labels_as_kv_strings,
    _lint_domain_env_vars,
    _lint_domain_reference_item,
    _parse_environment,
    _routers_with_certresolver,
    _routers_with_tls_enabled,
    _security_opt_has_no_new_privileges,
    _service_network_names,
    _user_is_non_root,
    check_api_insecure_for_dashboard,
    check_owasp_docker_baseline_weaknesses,
    check_rule_syntax_deprecated,
)


def _is_compose_file(file_path: Path) -> bool:
    parts = [part.lower() for part in file_path.parts]
    return "stacks" not in parts and file_path.name.lower() in {
        "docker-compose.yml",
        "docker-compose.yaml",
    }


def _service_labels_as_strings(service_config: dict[str, Any]) -> list[str]:
    labels = service_config.get("labels", [])
    return _labels_as_kv_strings(labels)


def check_baseline_hardening_for_compose(
    compose: dict[str, Any],
) -> list[LintResult]:
    """Enforce baseline container hardening for Docker Compose services.

    Baseline requirements (unless an explicit exception is allowlisted):
    - cap_drop includes ALL
    - security_opt includes no-new-privileges:true
    - user is explicitly set and is non-root
    """
    results: list[LintResult] = []
    services = compose.get("services", {})
    if not isinstance(services, dict):
        return results

    for service_name, service_config in services.items():
        if not isinstance(service_config, dict):
            continue

        if not _cap_drop_includes_all(service_config):
            results.append(
                LintResult(
                    severity=Severity.ERROR,
                    check_id="COMPOSE-HARDEN-001",
                    service=service_name,
                    message="Missing baseline hardening: cap_drop must include 'ALL'.",
                )
            )

        if not _security_opt_has_no_new_privileges(service_config):
            results.append(
                LintResult(
                    severity=Severity.ERROR,
                    check_id="COMPOSE-HARDEN-002",
                    service=service_name,
                    message="Missing baseline hardening: security_opt must include 'no-new-privileges:true'.",
                )
            )

        if service_name in _HARDENING_ALLOW_ROOT_SERVICES:
            continue

        if not _user_is_non_root(service_config.get("user")):
            results.append(
                LintResult(
                    severity=Severity.ERROR,
                    check_id="COMPOSE-HARDEN-003",
                    service=service_name,
                    message=(
                        "Missing baseline hardening: set a non-root user"
                        " (or add the service to the hardcoded allowlist if it truly requires root)."
                    ),
                )
            )

    return results


def check_domain_name_not_hardcoded_compose(
    compose: dict[str, Any],
) -> list[LintResult]:
    """Prevent hardcoding the base domain in Traefik Compose files."""
    results: list[LintResult] = []
    services = compose.get("services", {})

    for service_name, service_config in services.items():
        if not isinstance(service_config, dict) or not _is_traefik_service(service_name, service_config):
            continue

        env_vars = _parse_environment(service_config)
        results.extend(_lint_domain_env_vars(service_name, env_vars))

        command_list = _as_string_list(service_config.get("command", []))
        labels = _service_labels_as_strings(service_config)

        for item in [*command_list, *labels]:
            results.extend(_lint_domain_reference_item(service_name, item))

    return results


def check_docker_network_label_for_multi_network_traefik_services_compose(
    compose: dict[str, Any],
) -> list[LintResult]:
    """Ensure traefik.docker.network is set for multi-network, traefik-enabled services."""
    results: list[LintResult] = []
    services = compose.get("services", {})

    for service_name, service_config in services.items():
        if not isinstance(service_config, dict):
            continue

        networks = _service_network_names(service_config)
        if len(networks) <= 1:
            continue

        labels = _service_labels_as_strings(service_config)
        if "traefik.enable=true" not in labels:
            continue

        docker_network_label = next(
            (label for label in labels if label.startswith("traefik.docker.network=")),
            None,
        )
        if not docker_network_label:
            results.append(
                LintResult(
                    severity=Severity.ERROR,
                    check_id="TRAEFIK-NETWORK-001",
                    service=service_name,
                    message=(
                        "Service is traefik-enabled and attached to multiple networks, but "
                        "labels is missing 'traefik.docker.network=...'. "
                        "Pin the intended backend network to avoid wrong-network routing."
                    ),
                )
            )
            continue

        network_value = docker_network_label.split("=", 1)[1].strip()
        if not network_value or network_value not in set(networks):
            results.append(
                LintResult(
                    severity=Severity.ERROR,
                    check_id="TRAEFIK-NETWORK-002",
                    service=service_name,
                    message=(
                        "labels sets traefik.docker.network to a network that the service does not join. "
                        f"Value='{network_value}', networks={networks}."
                    ),
                )
            )

    return results


def check_certresolver_with_tls_compose(
    compose: dict[str, Any],
) -> list[LintResult]:
    """Check that routers with TLS enabled have a certresolver."""
    results: list[LintResult] = []
    services = compose.get("services", {})

    for service_name, service_config in services.items():
        if not isinstance(service_config, dict):
            continue

        labels_list = _service_labels_as_strings(service_config)
        if not labels_list:
            continue

        tls_routers = _routers_with_tls_enabled(labels_list)
        certresolver_routers = _routers_with_certresolver(labels_list)

        missing = tls_routers - certresolver_routers
        for router in missing:
            results.append(
                LintResult(
                    severity=Severity.WARN,
                    check_id="TRAEFIK-TLS-001",
                    service=service_name,
                    message=(
                        f"Router '{router}' has TLS enabled but no certresolver. "
                        "Add tls.certresolver label for automatic certificate management."
                    ),
                )
            )

    return results


def lint_compose_file(file_path: Path) -> list[LintResult]:
    """Run all lint checks on a Docker Compose file."""
    try:
        content = file_path.read_text(encoding="utf-8")
        compose = yaml.safe_load(content)
    except yaml.YAMLError as error:
        return [
            LintResult(
                severity=Severity.ERROR,
                check_id="YAML-PARSE-001",
                service="",
                message=f"Failed to parse YAML: {error}",
                file_path=str(file_path),
            )
        ]
    except OSError as error:
        return [
            LintResult(
                severity=Severity.ERROR,
                check_id="FILE-READ-001",
                service="",
                message=f"Failed to read file: {error}",
                file_path=str(file_path),
            )
        ]

    results: list[LintResult] = []

    if not isinstance(compose, dict):
        return results

    if not _is_compose_file(file_path):
        return results

    if "services" not in compose:
        return results

    compose_checks = [
        # ERROR-level checks
        check_baseline_hardening_for_compose,
        check_domain_name_not_hardcoded_compose,
        check_docker_network_label_for_multi_network_traefik_services_compose,
        check_owasp_docker_baseline_weaknesses,
        # WARN-level checks
        check_certresolver_with_tls_compose,
        check_rule_syntax_deprecated,
        # INFO-level checks
        check_api_insecure_for_dashboard,
    ]

    for check in compose_checks:
        results.extend(_run_check(file_path=file_path, compose=compose, check=check))

    return results


def main() -> int:  # pragma: no cover
    """CLI entry point."""
    return cli_main(
        description="Lint Docker Compose files for Traefik Compose compatibility.",
        epilog="""
Exit codes:
    0: All checks passed
    1: One or more ERROR-level issues found

Examples:
    python lint_compose.py docker-compose.yml
    python lint_compose.py compose/*.yml
        """,
        lint_fn=lint_compose_file,
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
