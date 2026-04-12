#!/usr/bin/env python3
"""Lint Docker Compose files for Traefik Swarm compatibility.

Validates that Docker Compose files are correctly configured for deployment
to Docker Swarm with the Traefik Swarm provider.

Checks are categorized as:
- Docker Swarm Compose: Compose syntax that behaves differently in Swarm
- Traefik Provider: Traefik-specific configuration for Swarm mode

Exit codes:
    0: All checks passed (no ERRORs)
    1: One or more ERROR-level issues found

Reference:
    - Traefik v3.6 Swarm Provider: https://doc.traefik.io/traefik/providers/swarm/
    - Christian Lempa boilerplate: https://github.com/ChristianLempa/boilerplates
"""

from __future__ import annotations

import re
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


def _is_swarm_stack_compose_file(file_path: Path) -> bool:
    parts = [part.lower() for part in file_path.parts]
    return "stacks" in parts and file_path.name.lower() in {
        "docker-compose.yml",
        "docker-compose.yaml",
    }


# Match ${DOMAIN_NAME}, ${DOMAIN_NAME_2}, ${DOMAIN_NAME?msg}, ${DOMAIN_NAME:?msg}, ${DOMAIN_NAME:-default}
_DOMAIN_VAR_PATTERN = re.compile(r"\$\{DOMAIN_NAME(?:_\d+)?(?:[:?][^}]+)?\}")


def _has_domain_var_reference(value: str) -> bool:
    return bool(_DOMAIN_VAR_PATTERN.search(value))


def _has_domain_var_default(value: str) -> bool:
    return "${DOMAIN_NAME" in value and ":-" in value


def _is_traefik_service(service_name: str, service_config: dict[str, Any]) -> bool:
    if service_name.lower() == "traefik":
        return True
    # Match actual Traefik proxy images, not images that happen to contain
    # "traefik" in the name (e.g. tiredofit/traefik-cloudflare-companion).
    image_lower = str(service_config.get("image", "")).lower()
    return image_lower.startswith("traefik:") or "/traefik:" in image_lower


def _parse_environment(service_config: dict[str, Any]) -> dict[str, str]:
    env = service_config.get("environment", {})
    if isinstance(env, dict):
        return {str(key): str(value) for key, value in env.items()}

    if isinstance(env, list):
        parsed: dict[str, str] = {}
        for item in env:
            if not isinstance(item, str) or "=" not in item:
                continue
            key, value = item.split("=", 1)
            parsed[key] = value
        return parsed

    return {}


def _as_string_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _labels_as_kv_strings(labels: Any) -> list[str]:
    """Convert labels (list or dict) to list of key=value strings."""
    if not labels:
        return []
    if isinstance(labels, list):
        return [str(label) for label in labels]
    if isinstance(labels, dict):
        return [f"{key}={value}" for key, value in labels.items()]
    return [str(labels)]


def _deploy_labels_as_strings(service_config: dict[str, Any]) -> list[str]:
    """Extract deploy.labels from service config and convert to key=value strings."""
    deploy = service_config.get("deploy", {})
    return _labels_as_kv_strings(deploy.get("labels", []))


def _router_name_from_label(label: str) -> str | None:
    parts = label.split(".")
    try:
        idx = parts.index("routers")
    except ValueError:
        return None
    if idx + 1 >= len(parts):
        return None
    return parts[idx + 1]


def _routers_with_tls_enabled(labels: list[str]) -> set[str]:
    routers: set[str] = set()
    for label in labels:
        label_lower = label.lower()
        if ".routers." not in label or ".tls=true" not in label_lower:
            continue
        router = _router_name_from_label(label)
        if router:
            routers.add(router)
    return routers


def _routers_with_certresolver(labels: list[str]) -> set[str]:
    routers: set[str] = set()
    for label in labels:
        if ".routers." not in label or ".certresolver" not in label.lower():
            continue
        router = _router_name_from_label(label)
        if router:
            routers.add(router)
    return routers


_DURATION_PART_RE = re.compile(r"(?P<num>\d+)(?P<unit>[smh])")


def _parse_duration_seconds(value: Any) -> int | None:
    if value is None:
        return None

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        if value < 0:
            return None
        return int(value)

    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None

    if text.isdigit():
        return int(text)

    matches = list(_DURATION_PART_RE.finditer(text))
    if not matches:
        return None

    if "".join(match.group(0) for match in matches) != text:
        return None

    unit_seconds = {"s": 1, "m": 60, "h": 3600}
    total = 0
    for match in matches:
        total += int(match.group("num")) * unit_seconds[match.group("unit")]
    return total


def check_healthcheck_timing_for_swarm_stacks(
    compose: dict[str, Any],
) -> list[LintResult]:
    """Validate Swarm stack healthcheck interval/timeout timing.

    Repo standard (docs/repository-standards/style-guides/docker-yaml-style-guide.md):
    - timeout < interval
    - interval - timeout >= 10s
    """
    results: list[LintResult] = []
    services = compose.get("services", {})
    if not isinstance(services, dict):
        return results

    for service_name, service_config in services.items():
        if not isinstance(service_config, dict):
            continue

        healthcheck = service_config.get("healthcheck")
        if not isinstance(healthcheck, dict):
            continue

        interval = _parse_duration_seconds(healthcheck.get("interval"))
        timeout = _parse_duration_seconds(healthcheck.get("timeout"))
        if interval is None or timeout is None:
            continue

        if timeout >= interval:
            results.append(
                LintResult(
                    severity=Severity.ERROR,
                    check_id="SWARM-HEALTHCHECK-001",
                    service=service_name,
                    message=(
                        f"Invalid healthcheck timing: timeout ({timeout}s) must be less than interval ({interval}s)."
                    ),
                )
            )
            continue

        if interval - timeout < 10:
            results.append(
                LintResult(
                    severity=Severity.ERROR,
                    check_id="SWARM-HEALTHCHECK-002",
                    service=service_name,
                    message=(
                        "Invalid healthcheck timing: interval - timeout must be at least 10s to prevent overlapping checks. "
                        f"Current: interval={interval}s, timeout={timeout}s."
                    ),
                )
            )

    return results


def _service_command_strings(service_config: dict[str, Any]) -> list[str]:
    command = service_config.get("command")
    if not command:
        return []
    if isinstance(command, list):
        return [str(command_item) for command_item in command]
    return [str(command)]


def _deploy_placement_constraints(service_config: dict[str, Any]) -> list[str]:
    deploy = service_config.get("deploy", {})
    if not isinstance(deploy, dict):
        return []

    placement = deploy.get("placement", {})
    if not isinstance(placement, dict):
        return []

    constraints = placement.get("constraints", [])
    if not constraints:
        return []
    if isinstance(constraints, list):
        return [str(constraint_item) for constraint_item in constraints]
    return [str(constraints)]


def _has_manager_role_constraint(constraints: list[str]) -> bool:
    return any(str(constraint_item).strip() == "node.role == manager" for constraint_item in constraints)


def check_socket_proxy_access_for_swarm_stacks(
    compose: dict[str, Any],
) -> list[LintResult]:
    """Enforce Swarm manager API access via socket-proxy.

    Applies only when a `socket-proxy` service exists in the compose file.
    """
    results: list[LintResult] = []
    services = compose.get("services", {})
    if not isinstance(services, dict):
        return results

    socket_proxy = services.get("socket-proxy")
    if not isinstance(socket_proxy, dict):
        return results

    constraints = _deploy_placement_constraints(socket_proxy)
    if not _has_manager_role_constraint(constraints):
        results.append(
            LintResult(
                severity=Severity.ERROR,
                check_id="SWARM-SOCKET-PROXY-001",
                service="socket-proxy",
                message=(
                    "socket-proxy must be placed on a Swarm manager (node.role == manager) so manager-only endpoints "
                    "required by the Swarm provider are available."
                ),
            )
        )

    expected = "--providers.swarm.endpoint=tcp://socket-proxy:2375"
    for service_name, service_config in services.items():
        if not isinstance(service_config, dict):
            continue
        if not _is_traefik_service(service_name, service_config):
            continue

        command_parts = _service_command_strings(service_config)
        if expected not in command_parts:
            results.append(
                LintResult(
                    severity=Severity.ERROR,
                    check_id="SWARM-TRAEFIK-PROVIDER-001",
                    service=service_name,
                    message=(
                        "Traefik must use the Swarm provider endpoint via socket-proxy. "
                        f"Add '{expected}' and avoid direct Docker socket mounts."
                    ),
                )
            )

    return results


# =============================================================================
# Check: /var/run/docker.sock mount restricted in Swarm stacks (ERROR)
# =============================================================================


_DOCKER_SOCKET_PATH = "/var/run/docker.sock"


def _volume_entry_has_docker_socket(volume: Any) -> bool:
    if isinstance(volume, str):
        return _DOCKER_SOCKET_PATH in volume

    if isinstance(volume, dict):
        source = str(volume.get("source", ""))
        target = str(volume.get("target", ""))
        return source == _DOCKER_SOCKET_PATH or target == _DOCKER_SOCKET_PATH

    return False


def _service_mounts_docker_socket(service_config: dict[str, Any]) -> bool:
    volumes = service_config.get("volumes", [])
    if not volumes:
        return False

    if isinstance(volumes, list):
        return any(_volume_entry_has_docker_socket(volume) for volume in volumes)

    return False


# Services permitted to bind-mount /var/run/docker.sock directly.
# socket-proxy is detected by name/image below; everything else goes here.
_DOCKER_SOCKET_ALLOWED_SERVICES: set[str] = {
    # Portainer Agent needs direct Docker socket access on every Swarm node
    # for full management (volume browsing, container console, node stats).
    # Official stack: downloads.portainer.io/ee-lts/portainer-agent-stack.yml
    "portainer-agent",
}


def _is_socket_proxy_service(service_name: str, service_config: dict[str, Any]) -> bool:
    if service_name.lower() == "socket-proxy":
        return True

    image = str(service_config.get("image", "")).lower()
    return "docker-socket-proxy" in image or "socket-proxy" in image


def _is_socket_mount_allowed(service_name: str, service_config: dict[str, Any]) -> bool:
    if _is_socket_proxy_service(service_name, service_config):
        return True
    return service_name in _DOCKER_SOCKET_ALLOWED_SERVICES


def check_docker_socket_mounts_restricted_for_swarm_stacks(
    compose: dict[str, Any],
) -> list[LintResult]:
    """Disallow direct Docker socket mounts in Swarm stacks.

    Decision: In ``stacks/**/docker-compose.yml``, only socket-proxy and explicitly
    allowlisted services (see ``_DOCKER_SOCKET_ALLOWED_SERVICES``) may mount
    ``/var/run/docker.sock``. All other services must use the socket-proxy endpoint.
    """
    results: list[LintResult] = []
    services = compose.get("services", {})
    if not isinstance(services, dict):
        return results

    for service_name, service_config in services.items():
        if not isinstance(service_config, dict):
            continue

        if not _service_mounts_docker_socket(service_config):
            continue

        if _is_socket_mount_allowed(service_name, service_config):
            continue

        results.append(
            LintResult(
                severity=Severity.ERROR,
                check_id="SWARM-DOCKER-SOCKET-001",
                service=service_name,
                message=(
                    "Direct Docker socket mount detected (/var/run/docker.sock). "
                    "In Swarm stacks, only socket-proxy and allowlisted services may "
                    "mount the Docker socket; all others must use the socket-proxy endpoint."
                ),
            )
        )

    return results


# =============================================================================
# Check: DOMAIN_NAME must not be hardcoded (ERROR)
# =============================================================================


def _domain_error(service_name: str, message: str) -> LintResult:
    return LintResult(
        severity=Severity.ERROR,
        check_id="TRAEFIK-DOMAIN-001",
        service=service_name,
        message=message,
    )


def _domain_env_keys(env_vars: dict[str, str]) -> list[str]:
    return [key for key in env_vars if key == "DOMAIN_NAME" or key.startswith("DOMAIN_NAME_")]


def _lint_domain_env_vars(service_name: str, env_vars: dict[str, str]) -> list[LintResult]:
    results: list[LintResult] = []

    for key in _domain_env_keys(env_vars):
        value = env_vars.get(key, "")
        if _has_domain_var_default(value):
            results.append(
                _domain_error(
                    service_name,
                    (
                        f"{key} uses a default fallback (:-), which hardcodes a domain in-repo. "
                        "Remove the fallback and require the value via ${DOMAIN_NAME?…} / ${DOMAIN_NAME_2?…} "
                        "from the deploy environment."
                    ),
                )
            )
            continue

        if "." in value and not _has_domain_var_reference(value):
            results.append(
                _domain_error(
                    service_name,
                    (
                        f"{key} appears to be a literal domain value. Do not hardcode domains in stack YAML; "
                        "use ${DOMAIN_NAME?…} (and ${DOMAIN_NAME_2?…} for secondary FQDN) and inject values at deploy time."
                    ),
                )
            )

    return results


def _lint_domain_reference_item(service_name: str, item: str) -> list[LintResult]:
    results: list[LintResult] = []

    if _has_domain_var_default(item):
        results.append(
            _domain_error(
                service_name,
                (
                    "DOMAIN_NAME is referenced with a default fallback (:-). "
                    "Remove defaults so domains are provided externally via the deploy environment."
                ),
            )
        )

    if "tls.domains" in item and "=" in item:
        rhs = item.split("=", 1)[1]
        if "." in rhs and not _has_domain_var_reference(rhs):
            results.append(
                _domain_error(
                    service_name,
                    (
                        "TLS domain appears to be hardcoded. Use ${DOMAIN_NAME?…} (and ${DOMAIN_NAME_2?…} if needed) "
                        "rather than embedding literal domains."
                    ),
                )
            )

    if "Host(`" in item and "." in item and not _has_domain_var_reference(item):
        results.append(
            _domain_error(
                service_name,
                (
                    "Router rule appears to hardcode a hostname. Use ${DOMAIN_NAME?…} / ${DOMAIN_NAME_2?…} variables "
                    "instead of embedding literal domains."
                ),
            )
        )

    return results


def check_domain_name_not_hardcoded(compose: dict[str, Any]) -> list[LintResult]:
    """Prevent hardcoding the base domain in Swarm Traefik stacks.

    Decision: DOMAIN_NAME (and optional DOMAIN_NAME_<n>) must be provided by the
    deployment environment (e.g., control-node .env export), not embedded as a
    default fallback (:-) or literal FQDN in the repo.
    """
    results: list[LintResult] = []
    services = compose.get("services", {})

    for service_name, service_config in services.items():
        if not isinstance(service_config, dict) or not _is_traefik_service(service_name, service_config):
            continue

        env_vars = _parse_environment(service_config)
        results.extend(_lint_domain_env_vars(service_name, env_vars))

        command_list = _as_string_list(service_config.get("command", []))
        deploy_labels = _as_string_list((service_config.get("deploy", {}) or {}).get("labels", []))

        for item in [*command_list, *deploy_labels]:
            results.extend(_lint_domain_reference_item(service_name, item))

    return results


# =============================================================================
# Check: Labels must be under deploy.labels (ERROR)
# =============================================================================


def check_labels_in_deploy_section(compose: dict[str, Any]) -> list[LintResult]:
    """Check that Traefik labels are under deploy.labels, not service-level labels.

    In Docker Swarm, the Swarm provider reads labels from the service spec,
    which are defined under deploy.labels. Service-level labels are placed
    on containers, which the Swarm provider does NOT read.

    Reference: https://doc.traefik.io/traefik/providers/swarm/#labels
    """
    results: list[LintResult] = []
    services = compose.get("services", {})

    for service_name, service_config in services.items():
        if not isinstance(service_config, dict):
            continue

        service_labels = service_config.get("labels", [])
        if not service_labels:
            continue

        # Check if any labels are Traefik-related
        labels_list = service_labels if isinstance(service_labels, list) else list(service_labels.keys())
        traefik_labels = [lbl for lbl in labels_list if "traefik" in str(lbl).lower()]

        if traefik_labels:
            results.append(
                LintResult(
                    severity=Severity.ERROR,
                    check_id="SWARM-LABELS-001",
                    service=service_name,
                    message=(
                        "Traefik labels are at service level 'labels:', but Swarm "
                        "provider reads from 'deploy.labels'. Move Traefik labels "
                        "under deploy.labels section."
                    ),
                )
            )

    return results


# =============================================================================
# Check: loadbalancer.server.port must be defined (ERROR)
# =============================================================================


def check_loadbalancer_port_defined(compose: dict[str, Any]) -> list[LintResult]:
    """Check that services with traefik.enable=true have loadbalancer.server.port.

    In Docker Swarm, the port is mandatory because Swarm doesn't expose
    container port metadata the same way standalone Docker does.

    Reference: https://doc.traefik.io/traefik/providers/swarm/#port
    """
    results: list[LintResult] = []
    services = compose.get("services", {})

    for service_name, service_config in services.items():
        if not isinstance(service_config, dict):
            continue

        deploy = service_config.get("deploy", {})
        deploy_labels = deploy.get("labels", [])

        if not deploy_labels:
            continue

        # Convert to list of strings for consistent handling
        labels_list = (
            deploy_labels
            if isinstance(deploy_labels, list)
            else [f"{key}={value}" for key, value in deploy_labels.items()]
        )

        # Check if traefik.enable=true
        is_enabled = any("traefik.enable=true" in str(lbl).lower() for lbl in labels_list)
        if not is_enabled:
            continue

        # Check if loadbalancer.server.port is defined
        has_port = any("loadbalancer.server.port" in str(lbl) for lbl in labels_list)
        if not has_port:
            results.append(
                LintResult(
                    severity=Severity.ERROR,
                    check_id="TRAEFIK-PORT-001",
                    service=service_name,
                    message=(
                        "Missing 'traefik.http.services.<name>.loadbalancer.server.port' "
                        "label. This is mandatory for Docker Swarm mode."
                    ),
                )
            )

    return results


# =============================================================================
# Check: traefik.docker.network pinned for multi-network services (ERROR)
# =============================================================================


def _service_network_names(service_config: dict[str, Any]) -> list[str]:
    networks = service_config.get("networks")
    if not networks:
        return []
    if isinstance(networks, str):
        return [networks]
    if isinstance(networks, list):
        return [str(network_name) for network_name in networks]
    if isinstance(networks, dict):
        return [str(network_name) for network_name in networks]
    return []


def check_docker_network_label_for_multi_network_traefik_services(
    compose: dict[str, Any],
) -> list[LintResult]:
    """Ensure traefik.docker.network is set for multi-network, traefik-enabled services.

    Traefik can attach to multiple networks. When a backend service also attaches to
    multiple networks, Traefik may select an unintended network unless a network is
    pinned via label.
    """
    results: list[LintResult] = []
    services = compose.get("services", {})

    for service_name, service_config in services.items():
        if not isinstance(service_config, dict):
            continue

        networks = _service_network_names(service_config)
        if len(networks) <= 1:
            continue

        deploy = service_config.get("deploy", {})
        if not isinstance(deploy, dict):
            continue

        labels = _labels_as_kv_strings(deploy.get("labels"))
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
                        "deploy.labels is missing 'traefik.docker.network=...'. "
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
                        "deploy.labels sets traefik.docker.network to a network that the service does not join. "
                        f"Value='{network_value}', networks={networks}."
                    ),
                )
            )

    return results


# =============================================================================
# Check: Use --providers.swarm not --providers.docker (ERROR)
# =============================================================================


def check_swarm_provider_not_docker(compose: dict[str, Any]) -> list[LintResult]:
    """Check that Traefik uses --providers.swarm not --providers.docker.

    The Docker provider reads container labels. The Swarm provider reads
    service labels from Docker Swarm service specs.

    Reference: https://doc.traefik.io/traefik/providers/swarm/
    """
    results: list[LintResult] = []
    services = compose.get("services", {})

    for service_name, service_config in services.items():
        if not isinstance(service_config, dict):
            continue

        command = service_config.get("command", [])
        if not command:
            continue

        command_list = command if isinstance(command, list) else [command]
        command_str = " ".join(str(command_item) for command_item in command_list)

        # Check for Docker provider usage
        if "--providers.docker" in command_str and "--providers.swarm" not in command_str:
            results.append(
                LintResult(
                    severity=Severity.ERROR,
                    check_id="TRAEFIK-PROVIDER-001",
                    service=service_name,
                    message=(
                        "Using '--providers.docker' but should use '--providers.swarm' for Docker Swarm deployments."
                    ),
                )
            )

    return results


# =============================================================================
# Check: network_mode: host not supported in Swarm (ERROR)
# =============================================================================


def check_network_mode_host(compose: dict[str, Any]) -> list[LintResult]:
    """Check that services don't use network_mode: host.

    network_mode: host is not supported in Docker Swarm mode.
    Use overlay networks or ports with mode: host instead.
    """
    results: list[LintResult] = []
    services = compose.get("services", {})

    for service_name, service_config in services.items():
        if not isinstance(service_config, dict):
            continue

        network_mode = service_config.get("network_mode", "")
        if network_mode == "host":
            results.append(
                LintResult(
                    severity=Severity.ERROR,
                    check_id="SWARM-NETWORK-001",
                    service=service_name,
                    message=(
                        "network_mode: host is not supported in Docker Swarm. "
                        "Use overlay networks or ports with mode: host."
                    ),
                )
            )

    return results


# =============================================================================
# Check: restart: invalid in Swarm, use deploy.restart_policy (ERROR)
# =============================================================================


def check_restart_policy_swarm(compose: dict[str, Any]) -> list[LintResult]:
    """Check that services use deploy.restart_policy instead of restart:.

    The restart: key is invalid in Docker Swarm mode — it is not applied
    by docker stack deploy. Use deploy.restart_policy instead.
    """
    results: list[LintResult] = []
    services = compose.get("services", {})

    for service_name, service_config in services.items():
        if not isinstance(service_config, dict):
            continue

        has_restart = "restart" in service_config
        deploy = service_config.get("deploy", {})
        has_deploy_restart = "restart_policy" in deploy

        if has_restart and not has_deploy_restart:
            results.append(
                LintResult(
                    severity=Severity.ERROR,
                    check_id="SWARM-RESTART-001",
                    service=service_name,
                    message=(
                        "restart: is invalid in Docker Swarm; not applied by docker stack deploy. "
                        "Use deploy.restart_policy instead."
                    ),
                )
            )

    return results


# =============================================================================
# Check: Use *_FILE env vars for secrets (WARN)
# =============================================================================


_SECRET_PATTERNS = ("PASSWORD", "TOKEN", "SECRET", "KEY", "API_KEY", "CREDENTIAL")


def _is_secret_related_env_var(env_name: str) -> bool:
    """Check if an env var name suggests it contains a secret."""
    upper = env_name.upper()
    return any(pattern in upper for pattern in _SECRET_PATTERNS)


def _references_secret_file(env_value: str) -> bool:
    """Check if the value references a secret file path."""
    if not env_value:
        return False
    # file:///run/secrets/... (Authentik pattern) or /run/secrets/... (direct path)
    return "file:///run/secrets/" in env_value or env_value.startswith("/run/secrets/")


def _env_var_needs_secret_warning(env_name: str, env_value: str) -> bool:
    """Check if an env var should trigger a secrets warning."""
    if env_name.endswith("_FILE"):
        return False
    if _references_secret_file(env_value):
        return False
    return _is_secret_related_env_var(env_name)


def check_secrets_file_pattern(compose: dict[str, Any]) -> list[LintResult]:
    """Check that services with secrets use *_FILE environment variables.

    Docker Swarm mounts secrets as files in /run/secrets/. Applications
    should read from these files using one of these patterns:
    - *_FILE suffix: CF_DNS_API_TOKEN_FILE=/run/secrets/cf_token
    - file:// URI: AUTHENTIK_SECRET_KEY=file:///run/secrets/authentik_secret_key
    """
    results: list[LintResult] = []

    for service_name, service_config in compose.get("services", {}).items():
        if not isinstance(service_config, dict) or not service_config.get("secrets"):
            continue

        for env_name, env_value in _parse_environment(service_config).items():
            if not _env_var_needs_secret_warning(env_name, env_value):
                continue
            results.append(
                LintResult(
                    severity=Severity.WARN,
                    check_id="SWARM-SECRETS-001",
                    service=service_name,
                    message=(
                        f"Environment variable '{env_name}' looks like a secret. "
                        f"Consider using '{env_name}_FILE=/run/secrets/<name>' pattern "
                        "for Docker Swarm secrets."
                    ),
                )
            )

    return results


# =============================================================================
# Check: OWASP Docker baseline weaknesses (ERROR/WARN)
# =============================================================================


_SENSITIVE_ENV_NAME_PATTERNS = (
    "PASSWORD",
    "TOKEN",
    "SECRET",
    "API_KEY",
    "KEY",
    "CREDENTIAL",
)


def _env_name_looks_sensitive(env_name: str) -> bool:
    upper = env_name.upper()
    return any(pattern in upper for pattern in _SENSITIVE_ENV_NAME_PATTERNS)


def _env_value_looks_like_literal_secret(value: str) -> bool:
    if not value:
        return False
    # Treat variable substitution as deploy-time injected (not a literal committed secret).
    if "$" in value:
        return False
    # File paths are not secret values; they should still generally use *_FILE, but
    # this check is focused on preventing literal secrets committed in YAML.
    if value.startswith("/run/secrets/"):
        return False
    # Some applications use the file:// URI scheme to read Docker Swarm secrets
    # from the same /run/secrets/ mount (e.g. Authentik uses file:///run/secrets/).
    return not value.startswith("file:///run/secrets/")


def _image_uses_digest(image: str) -> bool:
    return "@sha256:" in image


def _extract_image_tag(image: str) -> str | None:
    if "@" in image:
        return None

    last_slash = image.rfind("/")
    last_segment = image[(last_slash + 1) :]

    if ":" not in last_segment:
        return None

    tag = last_segment.split(":", 1)[1]
    return tag


def _check_privileged_container(*, service_name: str, service_config: dict[str, Any]) -> list[LintResult]:
    if service_config.get("privileged") is not True:
        return []
    return [
        LintResult(
            severity=Severity.ERROR,
            check_id="OWASP-DOCKER-PRIV-001",
            service=service_name,
            message=(
                "privileged: true increases container privileges and should be avoided. "
                "Use least-privilege settings (capabilities, read-only FS, etc.) instead."
            ),
        )
    ]


def _check_image_pinning(*, service_name: str, service_config: dict[str, Any]) -> list[LintResult]:
    image = str(service_config.get("image", "")).strip()
    if not image:
        return []

    if _image_uses_digest(image):
        return [
            LintResult(
                severity=Severity.ERROR,
                check_id="OWASP-DOCKER-IMAGE-003",
                service=service_name,
                message=(
                    "Image digest pinning (e.g., '@sha256:...') is not allowed in this repository. "
                    "Use an explicit version tag (prefer major version pinning when the image publishes it)."
                ),
            )
        ]

    tag = _extract_image_tag(image)
    if tag is None:
        return [
            LintResult(
                severity=Severity.ERROR,
                check_id="OWASP-DOCKER-IMAGE-001",
                service=service_name,
                message=(
                    "Image tag is not pinned (missing explicit tag). "
                    "Pin an explicit version tag (prefer major version pinning when the image publishes it)."
                ),
            )
        ]

    if tag.lower() == "latest":
        return [
            LintResult(
                severity=Severity.ERROR,
                check_id="OWASP-DOCKER-IMAGE-002",
                service=service_name,
                message=(
                    "Image tag ':latest' is not allowed. "
                    "Pin an explicit version tag (prefer major version pinning when the image publishes it)."
                ),
            )
        ]

    return []


def _check_literal_secret_env_values(*, service_name: str, service_config: dict[str, Any]) -> list[LintResult]:
    results: list[LintResult] = []
    env_vars = _parse_environment(service_config)
    for env_name, env_value in env_vars.items():
        if env_name.endswith("_FILE"):
            continue
        if not _env_name_looks_sensitive(env_name):
            continue
        if not _env_value_looks_like_literal_secret(env_value):
            continue

        results.append(
            LintResult(
                severity=Severity.ERROR,
                check_id="OWASP-DOCKER-SECRETS-001",
                service=service_name,
                message=(
                    f"Environment variable '{env_name}' looks secret-like and has a literal value committed in YAML. "
                    "Use Docker secrets and the *_FILE pattern (or inject via the deploy environment)."
                ),
            )
        )
    return results


def check_owasp_docker_baseline_weaknesses(compose: dict[str, Any]) -> list[LintResult]:
    """Flag high-signal baseline security weaknesses.

    This is intentionally conservative and avoids copying any OWASP guidance.
    It enforces repo-friendly baseline patterns that reduce common container
    security risks.

    External references:
    - https://owasp.org/www-project-docker-top-10/
    - https://github.com/OWASP/Docker-Security
    """
    services = compose.get("services", {})
    if not isinstance(services, dict):
        return []

    results: list[LintResult] = []

    for service_name, service_config in services.items():
        if not isinstance(service_config, dict):
            continue

        results.extend(
            _check_privileged_container(
                service_name=service_name,
                service_config=service_config,
            )
        )
        results.extend(
            _check_image_pinning(
                service_name=service_name,
                service_config=service_config,
            )
        )
        results.extend(
            _check_literal_secret_env_values(
                service_name=service_name,
                service_config=service_config,
            )
        )

    return results


# =============================================================================
# Check: baseline hardening for Swarm stacks (ERROR)
# =============================================================================


_HARDENING_ALLOW_ROOT_SERVICES: set[str] = {
    # Root exception list for services that require elevated
    # permissions/capabilities; keep until verified non-root support is viable.
    "crowdsec",
    "fail2ban",
    "coraza-waf",
    # Authentik worker requires root for Docker API operations
    # (outpost management, service discovery via socket-proxy).
    "authentik-worker",
    # Portainer Agent needs root for Docker socket and host volume access.
    "portainer-agent",
    # tiredofit images use s6-overlay which requires root at PID 1.
    "cloudflare-companion",
    # LinuxServer.io images use s6-overlay which requires root at PID 1.
    # Internal process runs as PUID/PGID.
    "sonarr",
    "radarr",
    "radarr-4k",
    "radarr-se",
    "radarr-4k-se",
    "radarr-concerts",
    "prowlarr",
    "lidarr",
    "bazarr",
    "bookshelf",
}

# Services allowed to use --api.insecure=true for internal API access.
# Dashboard should still be protected via a separate router + middleware.
_TRAEFIK_API_INSECURE_ALLOWED_SERVICES: set[str] = {
    # traefik-to-unifi requires internal overlay API access for DNS sync;
    # dashboard remains protected via Authentik on the external route.
    "traefik",
}


def _cap_drop_includes_all(service_config: dict[str, Any]) -> bool:
    cap_drop = service_config.get("cap_drop")
    if not isinstance(cap_drop, list):
        return False
    return any(str(cap).strip().upper() == "ALL" for cap in cap_drop)


def _security_opt_has_no_new_privileges(service_config: dict[str, Any]) -> bool:
    security_opt = service_config.get("security_opt")
    if not isinstance(security_opt, list):
        return False
    return any(str(opt).strip() == "no-new-privileges:true" for opt in security_opt)


def _user_is_non_root(user_value: Any) -> bool:
    if user_value is None:
        return False

    if isinstance(user_value, int):
        return user_value != 0

    if not isinstance(user_value, str):
        return False

    user = user_value.strip()
    if not user:
        return False

    # Common forms:
    # - "0" / "0:0" / "root" / "root:root"
    # - "1000" / "1000:1000" / "65532:65532"
    if user.lower() == "root":
        return False

    first_segment = user.split(":", 1)[0].strip()
    return not (first_segment.isdigit() and int(first_segment) == 0)


def check_baseline_hardening_for_swarm_stacks(
    compose: dict[str, Any],
) -> list[LintResult]:
    """Enforce baseline container hardening for Swarm stack services.

    This is scoped to Swarm stack files (called via lint_compose_file).

    Baseline requirements (unless an explicit exception is allowlisted):
    - cap_drop includes ALL
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
                    check_id="SWARM-HARDEN-001",
                    service=service_name,
                    message="Missing baseline hardening: cap_drop must include 'ALL'.",
                )
            )

        if service_name in _HARDENING_ALLOW_ROOT_SERVICES:
            continue

        if not _user_is_non_root(service_config.get("user")):
            results.append(
                LintResult(
                    severity=Severity.ERROR,
                    check_id="SWARM-HARDEN-003",
                    service=service_name,
                    message=(
                        "Missing baseline hardening: set a non-root user (or add the service to the hardcoded allowlist if it truly requires root)."
                    ),
                )
            )

    return results


# =============================================================================
# Check: security_opt invalid in Swarm (ERROR)
# =============================================================================


def check_security_opt_invalid(compose: dict[str, Any]) -> list[LintResult]:
    """Check that services don't include security_opt in Swarm stacks.

    security_opt is invalid in Docker Swarm mode — it is not applied by
    docker stack deploy.
    """
    results: list[LintResult] = []
    services = compose.get("services", {})

    for service_name, service_config in services.items():
        if not isinstance(service_config, dict):
            continue

        if "security_opt" in service_config:
            results.append(
                LintResult(
                    severity=Severity.ERROR,
                    check_id="SWARM-SECURITY-001",
                    service=service_name,
                    message=(
                        "security_opt is invalid in Swarm mode; not applied by docker stack deploy. Remove this key."
                    ),
                )
            )

    return results


# =============================================================================
# Check: invalid Swarm service keys (ERROR)
# =============================================================================

# Service-level keys that are invalid in Docker Swarm mode. docker stack deploy
# accepts them syntactically but does not apply them, giving users a false
# expectation of functionality. Each entry maps the key name to a tuple of
# (check_id, human-readable reason).
_INVALID_SWARM_SERVICE_KEYS: dict[str, tuple[str, str]] = {
    "container_name": (
        "SWARM-INVALID-001",
        "container_name is invalid in Swarm mode; not applied by docker stack deploy. "
        "Swarm auto-names replicas. Remove this key.",
    ),
    "build": (
        "SWARM-INVALID-002",
        "build is invalid in Swarm mode; not processed by docker stack deploy. "
        "Pre-build images and push to a registry.",
    ),
    "depends_on": (
        "SWARM-INVALID-003",
        "depends_on is invalid in Swarm mode; not applied by docker stack deploy. "
        "Swarm manages service scheduling independently. Remove this key.",
    ),
    "links": (
        "SWARM-INVALID-004",
        "links is invalid in Swarm mode; not applied by docker stack deploy. Use overlay networks instead.",
    ),
    "expose": (
        "SWARM-INVALID-005",
        "expose is invalid in Swarm mode; not applied by docker stack deploy. "
        "Services are auto-exposed on overlay networks. Remove this key.",
    ),
    "userns_mode": (
        "SWARM-INVALID-006",
        "userns_mode is not supported in Swarm mode. Remove this key.",
    ),
    "cgroup_parent": (
        "SWARM-INVALID-007",
        "cgroup_parent is not supported in Swarm mode. Remove this key.",
    ),
}


def check_invalid_swarm_keys(compose: dict[str, Any]) -> list[LintResult]:
    """Check that services do not use keys that are invalid in Swarm mode.

    These keys are accepted syntactically by docker-compose format but are
    not applied by ``docker stack deploy``, giving users a false expectation
    of functionality.
    """
    results: list[LintResult] = []
    services = compose.get("services", {})

    for service_name, service_config in services.items():
        if not isinstance(service_config, dict):
            continue

        for key, (check_id, message) in _INVALID_SWARM_SERVICE_KEYS.items():
            if key in service_config:
                results.append(
                    LintResult(
                        severity=Severity.ERROR,
                        check_id=check_id,
                        service=service_name,
                        message=message,
                    )
                )

    return results


# =============================================================================
# Check: certresolver with TLS (WARN)
# =============================================================================


def check_certresolver_with_tls(compose: dict[str, Any]) -> list[LintResult]:
    """Check that routers with TLS enabled have a certresolver.

    When TLS is enabled on a router, a certresolver should be specified
    to obtain certificates automatically.
    """
    results: list[LintResult] = []
    services = compose.get("services", {})

    for service_name, service_config in services.items():
        if not isinstance(service_config, dict):
            continue

        labels_list = _deploy_labels_as_strings(service_config)
        if not labels_list:
            continue

        tls_routers = _routers_with_tls_enabled(labels_list)
        certresolver_routers = _routers_with_certresolver(labels_list)

        # Check for TLS routers without certresolver
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


# =============================================================================
# Check: api.insecure for dashboard (ERROR/INFO)
# =============================================================================


def _get_command_string(service_config: dict[str, Any]) -> str:
    """Extract command as a single string from service config."""
    command = service_config.get("command", [])
    if not command:
        return ""
    command_list = command if isinstance(command, list) else [command]
    return " ".join(str(item) for item in command_list)


def check_api_insecure_for_dashboard(compose: dict[str, Any]) -> list[LintResult]:
    """Harden dashboard exposure by preventing insecure mode.

    In Swarm stacks, the dashboard should be exposed via a router + middleware
    (e.g., auth/TLS) and NOT via --api.insecure=true.
    """
    results: list[LintResult] = []

    for service_name, service_config in compose.get("services", {}).items():
        if not isinstance(service_config, dict):
            continue

        command_str = _get_command_string(service_config)
        if not command_str:
            continue

        has_dashboard = "--api.dashboard=true" in command_str or "--api=true" in command_str
        if not has_dashboard:
            continue

        insecure_true = "--api.insecure=true" in command_str
        insecure_false = "--api.insecure=false" in command_str

        # ERROR: insecure mode enabled (unless allowlisted)
        if insecure_true and service_name not in _TRAEFIK_API_INSECURE_ALLOWED_SERVICES:
            results.append(
                LintResult(
                    severity=Severity.ERROR,
                    check_id="TRAEFIK-API-001",
                    service=service_name,
                    message=(
                        "Dashboard/API is enabled and --api.insecure=true is set. "
                        "Disable insecure mode (set --api.insecure=false) and expose the dashboard "
                        "via a router + middleware (auth/TLS)."
                    ),
                )
            )
        # INFO: insecure mode not explicitly disabled
        elif not insecure_false and not insecure_true:
            results.append(
                LintResult(
                    severity=Severity.INFO,
                    check_id="TRAEFIK-API-002",
                    service=service_name,
                    message=(
                        "Dashboard/API is enabled but --api.insecure is not explicitly disabled. "
                        "Prefer setting --api.insecure=false and exposing the dashboard via a router + middleware."
                    ),
                )
            )

    return results


# =============================================================================
# Check: ruleSyntax deprecated (WARN)
# =============================================================================


def check_rule_syntax_deprecated(compose: dict[str, Any]) -> list[LintResult]:
    """Check for deprecated ruleSyntax option.

    The ruleSyntax option is deprecated in Traefik v3 and will be removed.
    """
    results: list[LintResult] = []
    services = compose.get("services", {})

    for service_name, service_config in services.items():
        if not isinstance(service_config, dict):
            continue

        command = service_config.get("command", [])
        if not command:
            continue

        command_list = command if isinstance(command, list) else [command]
        command_str = " ".join(str(command_item) for command_item in command_list)

        if "ruleSyntax" in command_str or "rulesyntax" in command_str.lower():
            results.append(
                LintResult(
                    severity=Severity.WARN,
                    check_id="TRAEFIK-DEPRECATED-001",
                    service=service_name,
                    message=(
                        "ruleSyntax is deprecated in Traefik v3 and will be removed. "
                        "Remove this option as v3 syntax is now the default."
                    ),
                )
            )

    return results


# =============================================================================
# Main lint function
# =============================================================================


def lint_compose_file(file_path: Path) -> list[LintResult]:
    """Run all lint checks on a Docker Compose file.

    Args:
        file_path: Path to the compose file

    Returns:
        List of all lint results from all checks
    """
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

    is_swarm_stack = _is_swarm_stack_compose_file(file_path)

    if is_swarm_stack and "name" in compose:
        results.append(
            LintResult(
                severity=Severity.ERROR,
                check_id="SWARM-SCHEMA-001",
                service="",
                message=(
                    "Top-level 'name' is not supported by 'docker stack deploy'. "
                    "Remove 'name:' from Swarm stack compose files under stacks/."
                ),
            )
        )

    if "services" not in compose:
        return results

    if not is_swarm_stack:
        return results

    swarm_checks = [
        # ERROR-level checks
        check_docker_socket_mounts_restricted_for_swarm_stacks,
        check_socket_proxy_access_for_swarm_stacks,
        check_healthcheck_timing_for_swarm_stacks,
        check_baseline_hardening_for_swarm_stacks,
        check_domain_name_not_hardcoded,
        check_labels_in_deploy_section,
        check_docker_network_label_for_multi_network_traefik_services,
        check_loadbalancer_port_defined,
        check_swarm_provider_not_docker,
        check_network_mode_host,
        check_owasp_docker_baseline_weaknesses,
        check_restart_policy_swarm,
        check_security_opt_invalid,
        check_invalid_swarm_keys,
        # WARN-level checks
        check_secrets_file_pattern,
        check_certresolver_with_tls,
        check_rule_syntax_deprecated,
        # INFO-level checks
        check_api_insecure_for_dashboard,
    ]

    for check in swarm_checks:
        results.extend(_run_check(file_path=file_path, compose=compose, check=check))

    return results


def main() -> int:
    """CLI entry point."""
    return cli_main(
        description="Lint Docker Compose files for Traefik Swarm compatibility.",
        epilog="""
Exit codes:
    0: All checks passed
    1: One or more ERROR-level issues found

Examples:
    python lint_swarm.py stacks/<stack>/docker-compose.yml
    python lint_swarm.py stacks/**/docker-compose.yml
        """,
        lint_fn=lint_compose_file,
    )


if __name__ == "__main__":
    sys.exit(main())
