"""Tests for Swarm linter.

TDD approach: tests written first, then implementation.
"""

from pathlib import Path
from unittest.mock import patch

import yaml

from scripts.linting.lint_swarm import (
    Severity,
    _as_string_list,
    _deploy_labels_as_strings,
    _deploy_placement_constraints,
    _env_name_looks_sensitive,
    _env_value_looks_like_literal_secret,
    _env_var_needs_secret_warning,
    _extract_image_tag,
    _has_domain_var_default,
    _has_domain_var_reference,
    _labels_as_kv_strings,
    _lint_domain_reference_item,
    _parse_duration_seconds,
    _parse_environment,
    _references_secret_file,
    _router_name_from_label,
    _routers_with_certresolver,
    _routers_with_tls_enabled,
    _security_opt_has_no_new_privileges,
    _service_command_strings,
    _service_mounts_docker_socket,
    _service_network_names,
    _user_is_non_root,
    _volume_entry_has_docker_socket,
    check_api_insecure_for_dashboard,
    check_baseline_hardening_for_swarm_stacks,
    check_certresolver_with_tls,
    check_docker_network_label_for_multi_network_traefik_services,
    check_docker_socket_mounts_restricted_for_swarm_stacks,
    check_domain_name_not_hardcoded,
    check_healthcheck_timing_for_swarm_stacks,
    check_invalid_swarm_keys,
    check_labels_in_deploy_section,
    check_loadbalancer_port_defined,
    check_network_mode_host,
    check_owasp_docker_baseline_weaknesses,
    check_restart_policy_swarm,
    check_rule_syntax_deprecated,
    check_secrets_file_pattern,
    check_security_opt_invalid,
    check_socket_proxy_access_for_swarm_stacks,
    check_swarm_provider_not_docker,
    lint_compose_file,
    main,
)

# Fixtures are defined in conftest.py to avoid W0621 warnings

# =============================================================================
# Test: Labels placement (ERROR)
# =============================================================================


class TestLabelsInDeploySection:
    """Traefik labels must be under deploy.labels for Swarm provider."""

    def test_labels_at_service_level_is_error(self, compose_labels_at_service_level):
        """Labels at service level should produce ERROR."""
        results = check_labels_in_deploy_section(compose_labels_at_service_level)
        assert len(results) == 1
        assert results[0].severity == Severity.ERROR
        assert "traefik" in results[0].service
        assert "deploy.labels" in results[0].message

    def test_labels_in_deploy_section_is_valid(self, valid_traefik_compose):
        """Labels in deploy.labels should produce no errors."""
        results = check_labels_in_deploy_section(valid_traefik_compose)
        assert len(results) == 0

    def test_no_labels_at_all_is_valid(self) -> None:
        """Service with no labels at all should produce no errors."""
        compose = {"services": {"traefik": {"image": "traefik:v3.6"}}}
        results = check_labels_in_deploy_section(compose)
        assert len(results) == 0


# =============================================================================
# Test: Loadbalancer port (ERROR)
# =============================================================================


class TestLoadbalancerPortDefined:
    """Services with traefik.enable=true must have loadbalancer.server.port."""

    def test_missing_port_is_error(self, missing_loadbalancer_port):
        """Missing loadbalancer.server.port should produce ERROR."""
        results = check_loadbalancer_port_defined(missing_loadbalancer_port)
        assert len(results) == 1
        assert results[0].severity == Severity.ERROR
        assert "loadbalancer.server.port" in results[0].message

    def test_port_defined_is_valid(self, valid_traefik_compose):
        """Service with loadbalancer.server.port defined should pass."""
        results = check_loadbalancer_port_defined(valid_traefik_compose)
        assert len(results) == 0

    def test_api_internal_service_still_needs_port(self) -> None:
        """Even api@internal service needs loadbalancer.server.port in Swarm."""
        compose = {
            "services": {
                "traefik": {
                    "image": "traefik:v3.6",
                    "deploy": {
                        "labels": [
                            "traefik.enable=true",
                            "traefik.http.routers.traefik-rtr.service=api@internal",
                        ],
                    },
                }
            }
        }
        results = check_loadbalancer_port_defined(compose)
        assert len(results) == 1
        assert results[0].severity == Severity.ERROR


# =============================================================================
# Test: traefik.docker.network for multi-network services (ERROR)
# =============================================================================


class TestDockerNetworkLabelForMultiNetworkTraefikServices:
    """Multi-network services exposed via Traefik must pin traefik.docker.network."""

    def test_missing_label_is_error(self, multi_network_traefik_enabled_service_missing_docker_network):
        results = check_docker_network_label_for_multi_network_traefik_services(
            multi_network_traefik_enabled_service_missing_docker_network
        )
        assert len(results) == 1
        assert results[0].severity == Severity.ERROR
        assert results[0].check_id == "TRAEFIK-NETWORK-001"

    def test_label_present_is_valid(self, multi_network_traefik_enabled_service_with_docker_network):
        results = check_docker_network_label_for_multi_network_traefik_services(
            multi_network_traefik_enabled_service_with_docker_network
        )
        assert len(results) == 0

    def test_label_points_to_wrong_network_is_error(
        self, multi_network_traefik_enabled_service_with_wrong_docker_network
    ):
        results = check_docker_network_label_for_multi_network_traefik_services(
            multi_network_traefik_enabled_service_with_wrong_docker_network
        )
        assert len(results) == 1
        assert results[0].severity == Severity.ERROR
        assert results[0].check_id == "TRAEFIK-NETWORK-002"


# =============================================================================
# Test: Swarm provider (ERROR)
# =============================================================================


class TestSwarmProviderNotDocker:
    """Must use --providers.swarm not --providers.docker for Swarm mode."""

    def test_docker_provider_is_error(self, docker_provider_instead_of_swarm):
        """Using --providers.docker instead of --providers.swarm is ERROR."""
        results = check_swarm_provider_not_docker(docker_provider_instead_of_swarm)
        assert len(results) == 1
        assert results[0].severity == Severity.ERROR
        assert "providers.swarm" in results[0].message

    def test_swarm_provider_is_valid(self, valid_traefik_compose):
        """Using --providers.swarm should pass."""
        results = check_swarm_provider_not_docker(valid_traefik_compose)
        assert len(results) == 0

    def test_no_command_is_valid(self) -> None:
        """Service without command should pass (not Traefik)."""
        compose = {"services": {"app": {"image": "nginx:1.27"}}}
        results = check_swarm_provider_not_docker(compose)
        assert len(results) == 0


# =============================================================================
# Test: OWASP Docker baseline weaknesses (ERROR)
# =============================================================================


class TestOwaspDockerBaselineWeaknesses:
    """High-signal baseline security weaknesses."""

    def test_privileged_is_error(self) -> None:
        compose = {
            "services": {
                "app": {
                    "image": "nginx:1.27",
                    "privileged": True,
                }
            }
        }
        results = check_owasp_docker_baseline_weaknesses(compose)
        assert any(result_item.check_id == "OWASP-DOCKER-PRIV-001" for result_item in results)

    def test_missing_image_tag_is_error(self) -> None:
        compose = {"services": {"app": {"image": "nginx"}}}
        results = check_owasp_docker_baseline_weaknesses(compose)
        assert any(result_item.check_id == "OWASP-DOCKER-IMAGE-001" for result_item in results)

    def test_latest_image_tag_is_error(self) -> None:
        compose = {"services": {"app": {"image": "nginx:latest"}}}
        results = check_owasp_docker_baseline_weaknesses(compose)
        assert any(result_item.check_id == "OWASP-DOCKER-IMAGE-002" for result_item in results)

    def test_image_digest_is_error(self) -> None:
        digest = "0" * 64
        compose = {"services": {"app": {"image": f"nginx@sha256:{digest}"}}}
        results = check_owasp_docker_baseline_weaknesses(compose)
        assert any(result_item.check_id == "OWASP-DOCKER-IMAGE-003" for result_item in results)

    def test_literal_secret_env_value_is_error(self) -> None:
        compose = {
            "services": {
                "db": {
                    "image": "postgres:16",
                    "environment": {
                        "POSTGRES_CREDENTIAL": "not-a-real-value",
                    },
                }
            }
        }
        results = check_owasp_docker_baseline_weaknesses(compose)
        assert any(result_item.check_id == "OWASP-DOCKER-SECRETS-001" for result_item in results)

    def test_env_var_reference_is_valid(self) -> None:
        compose = {
            "services": {
                "db": {
                    "image": "postgres:16",
                    "environment": {
                        "POSTGRES_CREDENTIAL": "${POSTGRES_CREDENTIAL}",
                    },
                }
            }
        }
        results = check_owasp_docker_baseline_weaknesses(compose)
        assert not any(result_item.check_id == "OWASP-DOCKER-SECRETS-001" for result_item in results)


# =============================================================================
# Test: Baseline hardening for Swarm stacks (ERROR)
# =============================================================================


class TestBaselineHardeningForSwarmStacks:
    def test_missing_cap_drop_all_is_error(self) -> None:
        compose = {
            "services": {
                "app": {
                    "image": "nginx:1.27",
                    "user": "1000:1000",
                }
            }
        }

        results = check_baseline_hardening_for_swarm_stacks(compose)
        assert any(result_item.check_id == "SWARM-HARDEN-001" for result_item in results)

    def test_missing_user_is_error(self) -> None:
        compose = {
            "services": {
                "app": {
                    "image": "nginx:1.27",
                    "cap_drop": ["ALL"],
                }
            }
        }

        results = check_baseline_hardening_for_swarm_stacks(compose)
        assert any(result_item.check_id == "SWARM-HARDEN-003" for result_item in results)

    def test_root_user_is_error(self) -> None:
        compose = {
            "services": {
                "app": {
                    "image": "nginx:1.27",
                    "user": "0:0",
                    "cap_drop": ["ALL"],
                }
            }
        }

        results = check_baseline_hardening_for_swarm_stacks(compose)
        assert any(result_item.check_id == "SWARM-HARDEN-003" for result_item in results)

    def test_allowlisted_root_services_skip_user_check(self) -> None:
        compose = {
            "services": {
                "crowdsec": {
                    "image": "crowdsecurity/crowdsec:v1",
                    "cap_drop": ["ALL"],
                }
            }
        }

        results = check_baseline_hardening_for_swarm_stacks(compose)
        assert not any(result_item.check_id == "SWARM-HARDEN-003" for result_item in results)

    def test_fully_hardened_service_is_valid(self) -> None:
        compose = {
            "services": {
                "app": {
                    "image": "nginx:1.27",
                    "user": "65532:65532",
                    "cap_drop": ["ALL"],
                }
            }
        }

        results = check_baseline_hardening_for_swarm_stacks(compose)
        assert results == []


# =============================================================================
# Test: Docker socket mount restriction (ERROR)
# =============================================================================


class TestDockerSocketMountsRestricted:
    """Docker socket mounts are restricted to socket-proxy and allowlisted services."""

    def test_allowlisted_service_with_socket_mount_is_valid(self) -> None:
        """Services in _DOCKER_SOCKET_ALLOWED_SERVICES may mount the Docker socket."""
        compose = {
            "services": {
                "portainer-agent": {
                    "image": "portainer/agent:2.33.7",
                    "volumes": ["/var/run/docker.sock:/var/run/docker.sock"],
                },
            }
        }
        results = check_docker_socket_mounts_restricted_for_swarm_stacks(compose)
        assert not any(result_item.check_id == "SWARM-DOCKER-SOCKET-001" for result_item in results)

    def test_non_allowlisted_service_with_socket_mount_is_error(self) -> None:
        """Services not in the allowlist must not mount the Docker socket."""
        compose = {
            "services": {
                "rogue-app": {
                    "image": "nginx:1.27",
                    "volumes": ["/var/run/docker.sock:/var/run/docker.sock:ro"],
                },
            }
        }
        results = check_docker_socket_mounts_restricted_for_swarm_stacks(compose)
        assert any(
            result_item.check_id == "SWARM-DOCKER-SOCKET-001" and result_item.severity == Severity.ERROR
            for result_item in results
        )

    def test_socket_proxy_with_socket_mount_is_valid(self) -> None:
        """socket-proxy is always permitted to mount the Docker socket."""
        compose = {
            "services": {
                "socket-proxy": {
                    "image": "wollomatic/socket-proxy:1",
                    "volumes": ["/var/run/docker.sock:/var/run/docker.sock:ro"],
                },
            }
        }
        results = check_docker_socket_mounts_restricted_for_swarm_stacks(compose)
        assert not any(result_item.check_id == "SWARM-DOCKER-SOCKET-001" for result_item in results)


# =============================================================================
# Test: Network mode host (ERROR)
# =============================================================================


class TestNetworkModeHost:
    """network_mode: host is not supported in Docker Swarm."""

    def test_network_mode_host_is_error(self, network_mode_host_service):
        """network_mode: host should produce ERROR."""
        results = check_network_mode_host(network_mode_host_service)
        assert len(results) == 1
        assert results[0].severity == Severity.ERROR
        assert "network_mode: host" in results[0].message

    def test_no_network_mode_is_valid(self, valid_traefik_compose):
        """Service without network_mode should pass."""
        results = check_network_mode_host(valid_traefik_compose)
        assert len(results) == 0


# =============================================================================
# Test: Restart policy (ERROR)
# =============================================================================


class TestRestartPolicySwarm:
    """restart: is invalid in Swarm, use deploy.restart_policy."""

    def test_restart_without_deploy_restart_policy_is_error(self, restart_instead_of_deploy_restart):
        """Using restart: without deploy.restart_policy is ERROR."""
        results = check_restart_policy_swarm(restart_instead_of_deploy_restart)
        assert len(results) == 1
        assert results[0].severity == Severity.ERROR
        assert "deploy.restart_policy" in results[0].message


# =============================================================================
# Test: Secrets file pattern (WARN)
# =============================================================================


class TestSecretsFilePattern:
    """Use *_FILE environment variables for Docker secrets."""

    def test_env_without_file_suffix_is_warn(self, env_var_without_file_suffix):
        """Env var for secret without _FILE suffix is WARN."""
        results = check_secrets_file_pattern(env_var_without_file_suffix)
        assert len(results) == 1
        assert results[0].severity == Severity.WARN
        assert "_FILE" in results[0].message

    def test_file_suffix_is_valid(self, valid_traefik_compose):
        """Env var with _FILE suffix should pass."""
        results = check_secrets_file_pattern(valid_traefik_compose)
        assert len(results) == 0


# =============================================================================
# Test: DOMAIN_NAME must not be hardcoded (ERROR)
# =============================================================================


class TestDomainNameNotHardcoded:
    """DOMAIN_NAME should be provided at deploy time, not hardcoded in YAML."""

    def test_domain_var_reference_matches_valid_syntax(self) -> None:
        assert _has_domain_var_reference("${DOMAIN_NAME}")
        assert _has_domain_var_reference("${DOMAIN_NAME_2}")
        assert _has_domain_var_reference("prefix-${DOMAIN_NAME}-suffix")
        assert _has_domain_var_reference("${DOMAIN_NAME?DOMAIN_NAME is required}")
        assert _has_domain_var_reference("${DOMAIN_NAME:?DOMAIN_NAME is required}")
        assert _has_domain_var_reference("${DOMAIN_NAME:-example.com}")

    def test_domain_var_reference_rejects_invalid_syntax(self) -> None:
        assert not _has_domain_var_reference("${DOMAIN_NAMEabc}")

    def test_domain_name_with_default_fallback_is_error(self) -> None:
        compose = {
            "services": {
                "traefik": {
                    "image": "traefik:v3.6",
                    "environment": ["DOMAIN_NAME=${DOMAIN_NAME:-example.com}"],
                }
            }
        }
        results = check_domain_name_not_hardcoded(compose)
        assert any(
            result_item.check_id == "TRAEFIK-DOMAIN-001" and result_item.severity == Severity.ERROR
            for result_item in results
        )

    def test_domain_name_literal_value_is_error(self) -> None:
        compose = {
            "services": {
                "traefik": {
                    "image": "traefik:v3.6",
                    "environment": ["DOMAIN_NAME=example.com"],
                }
            }
        }
        results = check_domain_name_not_hardcoded(compose)
        assert any(
            result_item.check_id == "TRAEFIK-DOMAIN-001" and result_item.severity == Severity.ERROR
            for result_item in results
        )

    def test_tls_domain_literal_is_error(self) -> None:
        compose = {
            "services": {
                "traefik": {
                    "image": "traefik:v3.6",
                    "command": [
                        "--providers.swarm=true",
                        "--entrypoints.websecure.http.tls.domains[0].main=example.com",
                    ],
                }
            }
        }
        results = check_domain_name_not_hardcoded(compose)
        assert any(
            result_item.check_id == "TRAEFIK-DOMAIN-001" and result_item.severity == Severity.ERROR
            for result_item in results
        )

    def test_required_domain_name_and_secondary_are_valid(self) -> None:
        compose = {
            "services": {
                "traefik": {
                    "image": "traefik:v3.6",
                    "environment": [
                        "DOMAIN_NAME=${DOMAIN_NAME?DOMAIN_NAME is required}",
                        "DOMAIN_NAME_2=${DOMAIN_NAME_2?DOMAIN_NAME_2 is required}",
                    ],
                    "command": [
                        "--providers.swarm=true",
                        "--entrypoints.websecure.http.tls.domains[0].main=${DOMAIN_NAME?DOMAIN_NAME is required}",
                        "--entrypoints.websecure.http.tls.domains[0].sans=*.${DOMAIN_NAME?DOMAIN_NAME is required}",
                    ],
                    "deploy": {
                        "labels": [
                            "traefik.enable=true",
                            "traefik.http.routers.traefik-rtr.rule=Host(`traefik.${DOMAIN_NAME?DOMAIN_NAME is required}`)",
                            "traefik.http.routers.alt-rtr.rule=Host(`alt.${DOMAIN_NAME_2?DOMAIN_NAME_2 is required}`)",
                        ]
                    },
                }
            }
        }
        results = check_domain_name_not_hardcoded(compose)
        assert len(results) == 0


# =============================================================================
# Test: Full lint integration
# =============================================================================


class TestLintComposeFile:
    """Integration test for full compose file linting."""

    def test_valid_compose_has_no_errors(self, valid_traefik_compose, tmp_path):
        """Valid compose file should produce no ERROR results."""
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text(yaml.dump(valid_traefik_compose))

        results = lint_compose_file(compose_file)
        errors = [result_item for result_item in results if result_item.severity == Severity.ERROR]
        assert len(errors) == 0

    def test_non_stack_compose_is_skipped(self, tmp_path: Path) -> None:
        """Non-stack compose files are skipped by the Swarm linter."""
        bad_compose = {
            "services": {
                "traefik": {
                    "image": "traefik:v3.6",
                    "command": ["--providers.docker=true"],
                    "restart": "unless-stopped",
                    "labels": ["traefik.enable=true"],
                }
            }
        }
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text(yaml.dump(bad_compose))

        results = lint_compose_file(compose_file)
        assert results == []

    def test_swarm_stack_with_name_is_error(self, tmp_path: Path) -> None:
        """Top-level name should be ERROR for Swarm stack files."""
        bad_compose = {
            "name": "edge-traefik",
            "services": {"traefik": {"image": "traefik:v3.6"}},
        }
        compose_file = tmp_path / "stacks" / "edge" / "traefik" / "docker-compose.yml"
        compose_file.parent.mkdir(parents=True, exist_ok=True)
        compose_file.write_text(yaml.dump(bad_compose))

        results = lint_compose_file(compose_file)
        assert any(
            result_item.check_id == "SWARM-SCHEMA-001" and result_item.severity == Severity.ERROR
            for result_item in results
        )

    def test_swarm_stack_docker_socket_mount_outside_socket_proxy_is_error(self, tmp_path: Path) -> None:
        """Only socket-proxy may mount /var/run/docker.sock in Swarm stacks."""
        bad_compose = {
            "services": {
                "traefik": {
                    "image": "traefik:v3.6",
                    "volumes": ["/var/run/docker.sock:/var/run/docker.sock:ro"],
                },
                "socket-proxy": {
                    "image": "ghcr.io/tecnativa/docker-socket-proxy:0.2.0",
                    "volumes": ["/var/run/docker.sock:/var/run/docker.sock:ro"],
                },
            }
        }

        compose_file = tmp_path / "stacks" / "edge" / "traefik" / "docker-compose.yml"
        compose_file.parent.mkdir(parents=True, exist_ok=True)
        compose_file.write_text(yaml.dump(bad_compose))

        results = lint_compose_file(compose_file)
        assert any(
            result_item.check_id == "SWARM-DOCKER-SOCKET-001" and result_item.severity == Severity.ERROR
            for result_item in results
        )

    def test_swarm_stack_docker_socket_mount_only_on_socket_proxy_is_valid(self, tmp_path: Path) -> None:
        """socket-proxy may mount /var/run/docker.sock in Swarm stacks."""
        ok_compose = {
            "services": {
                "traefik": {
                    "image": "traefik:v3.6",
                },
                "socket-proxy": {
                    "image": "ghcr.io/tecnativa/docker-socket-proxy:0.2.0",
                    "volumes": ["/var/run/docker.sock:/var/run/docker.sock:ro"],
                },
            }
        }

        compose_file = tmp_path / "stacks" / "edge" / "traefik" / "docker-compose.yml"
        compose_file.parent.mkdir(parents=True, exist_ok=True)
        compose_file.write_text(yaml.dump(ok_compose))

        results = lint_compose_file(compose_file)
        assert not any(result_item.check_id == "SWARM-DOCKER-SOCKET-001" for result_item in results)

    def test_swarm_stack_healthcheck_timeout_must_be_less_than_interval_is_error(self, tmp_path: Path) -> None:
        bad_compose = {
            "services": {
                "dozzle": {
                    "image": "amir20/dozzle:v8",
                    "healthcheck": {
                        "test": ["CMD", "/dozzle", "healthcheck"],
                        "interval": "10s",
                        "timeout": "10s",
                    },
                }
            }
        }

        compose_file = tmp_path / "stacks" / "edge" / "traefik" / "docker-compose.yml"
        compose_file.parent.mkdir(parents=True, exist_ok=True)
        compose_file.write_text(yaml.dump(bad_compose))

        results = lint_compose_file(compose_file)
        assert any(
            result_item.check_id == "SWARM-HEALTHCHECK-001" and result_item.severity == Severity.ERROR
            for result_item in results
        )

    def test_swarm_stack_healthcheck_interval_timeout_gap_must_be_at_least_10_seconds_is_error(
        self, tmp_path: Path
    ) -> None:
        bad_compose = {
            "services": {
                "dozzle": {
                    "image": "amir20/dozzle:v8",
                    "healthcheck": {
                        "test": ["CMD", "/dozzle", "healthcheck"],
                        "interval": "15s",
                        "timeout": "10s",
                    },
                }
            }
        }

        compose_file = tmp_path / "stacks" / "edge" / "traefik" / "docker-compose.yml"
        compose_file.parent.mkdir(parents=True, exist_ok=True)
        compose_file.write_text(yaml.dump(bad_compose))

        results = lint_compose_file(compose_file)
        assert any(
            result_item.check_id == "SWARM-HEALTHCHECK-002" and result_item.severity == Severity.ERROR
            for result_item in results
        )

    def test_non_stack_compose_healthcheck_timing_is_not_enforced(self, tmp_path: Path) -> None:
        bad_compose = {
            "services": {
                "dozzle": {
                    "image": "amir20/dozzle:v8",
                    "healthcheck": {
                        "test": ["CMD", "/dozzle", "healthcheck"],
                        "interval": "10s",
                        "timeout": "10s",
                    },
                }
            }
        }

        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text(yaml.dump(bad_compose))

        results = lint_compose_file(compose_file)
        assert not any(result_item.check_id.startswith("SWARM-HEALTHCHECK-") for result_item in results)

    def test_swarm_stack_socket_proxy_must_be_manager_placed_is_error(self, tmp_path: Path) -> None:
        bad_compose = {
            "services": {
                "socket-proxy": {
                    "image": "wollomatic/socket-proxy:1",
                    "volumes": ["/var/run/docker.sock:/var/run/docker.sock:ro"],
                    "deploy": {
                        "placement": {
                            "constraints": [
                                "node.labels.socket_proxy == true",
                            ]
                        }
                    },
                }
            }
        }

        compose_file = tmp_path / "stacks" / "edge" / "traefik" / "docker-compose.yml"
        compose_file.parent.mkdir(parents=True, exist_ok=True)
        compose_file.write_text(yaml.dump(bad_compose))

        results = lint_compose_file(compose_file)
        assert any(
            result_item.check_id == "SWARM-SOCKET-PROXY-001" and result_item.severity == Severity.ERROR
            for result_item in results
        )

    def test_swarm_stack_traefik_swarm_endpoint_must_use_socket_proxy_is_error(self, tmp_path: Path) -> None:
        bad_compose = {
            "services": {
                "socket-proxy": {
                    "image": "wollomatic/socket-proxy:1",
                    "volumes": ["/var/run/docker.sock:/var/run/docker.sock:ro"],
                    "deploy": {"placement": {"constraints": ["node.role == manager"]}},
                },
                "traefik": {
                    "image": "traefik:v3.6",
                    "command": [
                        "--providers.swarm=true",
                        "--providers.swarm.endpoint=tcp://docker:2375",
                    ],
                },
            }
        }

        compose_file = tmp_path / "stacks" / "edge" / "traefik" / "docker-compose.yml"
        compose_file.parent.mkdir(parents=True, exist_ok=True)
        compose_file.write_text(yaml.dump(bad_compose))

        results = lint_compose_file(compose_file)
        assert any(
            result_item.check_id == "SWARM-TRAEFIK-PROVIDER-001" and result_item.severity == Severity.ERROR
            for result_item in results
        )

    def test_swarm_stack_socket_proxy_enforcement_is_skipped_when_absent(self, tmp_path: Path) -> None:
        compose = {
            "services": {
                "traefik": {
                    "image": "traefik:v3.6",
                    "command": ["--providers.swarm=true"],
                }
            }
        }

        compose_file = tmp_path / "stacks" / "edge" / "traefik" / "docker-compose.yml"
        compose_file.parent.mkdir(parents=True, exist_ok=True)
        compose_file.write_text(yaml.dump(compose))

        results = lint_compose_file(compose_file)
        assert not any(
            result_item.check_id.startswith("SWARM-SOCKET-PROXY-")
            or result_item.check_id.startswith("SWARM-TRAEFIK-PROVIDER-")
            for result_item in results
        )


# =============================================================================
# Test: security_opt invalid in Swarm (ERROR)
# =============================================================================


class TestSecurityOptInvalid:
    """security_opt is invalid in Docker Swarm mode."""

    def test_security_opt_is_error(self) -> None:
        """security_opt should produce ERROR."""
        compose = {
            "services": {
                "traefik": {
                    "image": "traefik:v3.6",
                    "security_opt": ["no-new-privileges:true"],
                }
            }
        }
        results = check_security_opt_invalid(compose)
        assert len(results) == 1
        assert results[0].severity == Severity.ERROR
        assert "security_opt" in results[0].message

    def test_no_security_opt_is_valid(self, valid_traefik_compose):
        """Service without security_opt should pass."""
        results = check_security_opt_invalid(valid_traefik_compose)
        assert len(results) == 0


# =============================================================================
# Test: certresolver with TLS (WARN)
# =============================================================================


class TestCertresolverWithTls:
    """When TLS is enabled, certresolver should be specified."""

    def test_tls_without_certresolver_is_warn(self) -> None:
        """TLS enabled without certresolver should produce WARN."""
        compose = {
            "services": {
                "app": {
                    "image": "nginx:1.27",
                    "deploy": {
                        "labels": [
                            "traefik.enable=true",
                            "traefik.http.routers.app-rtr.tls=true",
                            "traefik.http.routers.app-rtr.rule=Host(`app.example.com`)",
                        ],
                    },
                }
            }
        }
        results = check_certresolver_with_tls(compose)
        assert len(results) == 1
        assert results[0].severity == Severity.WARN
        assert "certresolver" in results[0].message

    def test_tls_with_certresolver_is_valid(self) -> None:
        """TLS enabled with certresolver should pass."""
        compose = {
            "services": {
                "app": {
                    "image": "nginx:1.27",
                    "deploy": {
                        "labels": [
                            "traefik.enable=true",
                            "traefik.http.routers.app-rtr.tls=true",
                            "traefik.http.routers.app-rtr.tls.certresolver=dns-cloudflare",
                        ],
                    },
                }
            }
        }
        results = check_certresolver_with_tls(compose)
        assert len(results) == 0


# =============================================================================
# Test: api.insecure for dashboard (INFO)
# =============================================================================


class TestApiInsecureForDashboard:
    """The Traefik dashboard should not be exposed insecurely."""

    def test_dashboard_with_api_insecure_true_is_error(self) -> None:
        """Dashboard enabled with --api.insecure=true should produce ERROR."""
        compose = {
            "services": {
                "traefik-test": {  # Non-allowlisted service name
                    "image": "traefik:v3.6",
                    "command": [
                        "--api.dashboard=true",
                        "--api.insecure=true",
                    ],
                    "ports": [{"target": 8080, "published": 8080}],
                }
            }
        }
        results = check_api_insecure_for_dashboard(compose)
        assert len(results) == 1
        assert results[0].severity == Severity.ERROR
        assert "api.insecure" in results[0].message

    def test_dashboard_with_api_insecure_true_allowlisted_passes(self) -> None:
        """Allowlisted service with --api.insecure=true should pass."""
        compose = {
            "services": {
                "traefik": {  # Allowlisted in _TRAEFIK_API_INSECURE_ALLOWED_SERVICES
                    "image": "traefik:v3.6",
                    "command": [
                        "--api.dashboard=true",
                        "--api.insecure=true",
                    ],
                }
            }
        }
        results = check_api_insecure_for_dashboard(compose)
        assert len(results) == 0

    def test_dashboard_with_api_insecure_false_is_valid(self) -> None:
        """Dashboard with --api.insecure=false should pass."""
        compose = {
            "services": {
                "traefik": {
                    "image": "traefik:v3.6",
                    "command": [
                        "--api.dashboard=true",
                        "--api.insecure=false",
                    ],
                }
            }
        }
        results = check_api_insecure_for_dashboard(compose)
        assert len(results) == 0


# =============================================================================
# Test: ruleSyntax deprecated (WARN)
# =============================================================================


class TestRuleSyntaxDeprecated:
    """ruleSyntax is deprecated in Traefik v3."""

    def test_rule_syntax_is_warn(self) -> None:
        """Using ruleSyntax should produce WARN."""
        compose = {
            "services": {
                "traefik": {
                    "image": "traefik:v3.6",
                    "command": [
                        "--providers.swarm=true",
                        "--providers.swarm.ruleSyntax=v3",
                    ],
                }
            }
        }
        results = check_rule_syntax_deprecated(compose)
        assert len(results) == 1
        assert results[0].severity == Severity.WARN
        assert "ruleSyntax" in results[0].message
        assert "deprecated" in results[0].message.lower()

    def test_no_rule_syntax_is_valid(self, valid_traefik_compose):
        """Service without ruleSyntax should pass."""
        results = check_rule_syntax_deprecated(valid_traefik_compose)
        assert len(results) == 0


# =============================================================================
# Test: invalid Swarm service keys (ERROR)
# =============================================================================


class TestInvalidSwarmKeys:
    """Service keys that are invalid in Swarm mode must produce ERROR."""

    def test_container_name_is_error(self) -> None:
        """container_name is invalid in Swarm; not applied by docker stack deploy."""
        compose = {"services": {"app": {"image": "nginx:1.27", "container_name": "my-app"}}}
        results = check_invalid_swarm_keys(compose)
        assert len(results) == 1
        assert results[0].severity == Severity.ERROR
        assert results[0].check_id == "SWARM-INVALID-001"
        assert "container_name" in results[0].message

    def test_build_is_error(self) -> None:
        """Build is invalid in Swarm; not processed by docker stack deploy."""
        compose = {"services": {"app": {"image": "nginx:1.27", "build": "."}}}
        results = check_invalid_swarm_keys(compose)
        assert len(results) == 1
        assert results[0].severity == Severity.ERROR
        assert results[0].check_id == "SWARM-INVALID-002"
        assert "build" in results[0].message

    def test_depends_on_is_error(self) -> None:
        """depends_on is invalid in Swarm; not applied by docker stack deploy."""
        compose = {"services": {"app": {"image": "nginx:1.27", "depends_on": ["db"]}}}
        results = check_invalid_swarm_keys(compose)
        assert len(results) == 1
        assert results[0].severity == Severity.ERROR
        assert results[0].check_id == "SWARM-INVALID-003"
        assert "depends_on" in results[0].message

    def test_links_is_error(self) -> None:
        """Links is invalid in Swarm; not applied by docker stack deploy."""
        compose = {"services": {"app": {"image": "nginx:1.27", "links": ["db"]}}}
        results = check_invalid_swarm_keys(compose)
        assert len(results) == 1
        assert results[0].severity == Severity.ERROR
        assert results[0].check_id == "SWARM-INVALID-004"
        assert "links" in results[0].message

    def test_expose_is_error(self) -> None:
        """Expose is invalid in Swarm; not applied by docker stack deploy."""
        compose = {"services": {"app": {"image": "nginx:1.27", "expose": ["8080"]}}}
        results = check_invalid_swarm_keys(compose)
        assert len(results) == 1
        assert results[0].severity == Severity.ERROR
        assert results[0].check_id == "SWARM-INVALID-005"
        assert "expose" in results[0].message

    def test_userns_mode_is_error(self) -> None:
        """userns_mode is not supported in Swarm mode."""
        compose = {"services": {"app": {"image": "nginx:1.27", "userns_mode": "host"}}}
        results = check_invalid_swarm_keys(compose)
        assert len(results) == 1
        assert results[0].severity == Severity.ERROR
        assert results[0].check_id == "SWARM-INVALID-006"
        assert "userns_mode" in results[0].message

    def test_cgroup_parent_is_error(self) -> None:
        """cgroup_parent is not supported in Swarm mode."""
        compose = {"services": {"app": {"image": "nginx:1.27", "cgroup_parent": "m-executor-abcd"}}}
        results = check_invalid_swarm_keys(compose)
        assert len(results) == 1
        assert results[0].severity == Severity.ERROR
        assert results[0].check_id == "SWARM-INVALID-007"
        assert "cgroup_parent" in results[0].message

    def test_multiple_invalid_keys_produces_multiple_errors(self) -> None:
        """Multiple invalid keys should each produce an ERROR."""
        compose = {
            "services": {
                "app": {
                    "image": "nginx:1.27",
                    "container_name": "my-app",
                    "build": ".",
                    "depends_on": ["db"],
                }
            }
        }
        results = check_invalid_swarm_keys(compose)
        assert len(results) == 3
        assert all(result.severity == Severity.ERROR for result in results)
        check_ids = {result.check_id for result in results}
        assert check_ids == {"SWARM-INVALID-001", "SWARM-INVALID-002", "SWARM-INVALID-003"}

    def test_no_invalid_keys_is_valid(self, valid_traefik_compose):
        """Service without any invalid Swarm keys should pass."""
        results = check_invalid_swarm_keys(valid_traefik_compose)
        assert len(results) == 0

    def test_swarm_supported_keys_not_flagged(self) -> None:
        """Keys valid in Swarm API v1.41+ must not be flagged."""
        compose = {
            "services": {
                "app": {
                    "image": "nginx:1.27",
                    "cap_add": ["NET_ADMIN"],
                    "cap_drop": ["ALL"],
                    "tmpfs": ["/tmp"],
                    "extra_hosts": ["host.docker.internal:host-gateway"],
                    "sysctls": {"net.core.somaxconn": "1024"},
                }
            }
        }
        results = check_invalid_swarm_keys(compose)
        assert len(results) == 0


# =============================================================================
# Test: Helper functions — _parse_environment
# =============================================================================


class TestParseEnvironment:
    def test_dict_env(self) -> None:
        result = _parse_environment({"environment": {"FOO": "bar"}})
        assert result == {"FOO": "bar"}

    def test_list_env_with_equals(self) -> None:
        result = _parse_environment({"environment": ["FOO=bar", "BAZ=qux"]})
        assert result == {"FOO": "bar", "BAZ": "qux"}

    def test_list_env_skips_non_string_and_no_equals(self) -> None:
        result = _parse_environment({"environment": [123, "NO_EQUALS", "GOOD=val"]})
        assert result == {"GOOD": "val"}

    def test_non_dict_non_list_env_returns_empty(self) -> None:
        result = _parse_environment({"environment": "not-a-dict-or-list"})
        assert result == {}

    def test_missing_env_returns_empty(self) -> None:
        result = _parse_environment({})
        assert result == {}


# =============================================================================
# Test: Helper functions — _as_string_list
# =============================================================================


class TestAsStringList:
    def test_empty_value(self) -> None:
        assert _as_string_list(None) == []
        assert _as_string_list([]) == []
        assert _as_string_list("") == []

    def test_list_value(self) -> None:
        assert _as_string_list(["a", "b"]) == ["a", "b"]

    def test_single_value(self) -> None:
        assert _as_string_list("single") == ["single"]

    def test_integer_value(self) -> None:
        assert _as_string_list(42) == ["42"]


# =============================================================================
# Test: Helper functions — _labels_as_kv_strings
# =============================================================================


class TestLabelsAsKvStrings:
    def test_list_labels(self) -> None:
        result = _labels_as_kv_strings(["traefik.enable=true"])
        assert result == ["traefik.enable=true"]

    def test_dict_labels(self) -> None:
        result = _labels_as_kv_strings({"traefik.enable": "true"})
        assert result == ["traefik.enable=true"]

    def test_empty_labels(self) -> None:
        assert _labels_as_kv_strings(None) == []
        assert _labels_as_kv_strings([]) == []

    def test_scalar_fallback(self) -> None:
        result = _labels_as_kv_strings("traefik.enable=true")
        assert result == ["traefik.enable=true"]


# =============================================================================
# Test: Helper functions — _router_name_from_label
# =============================================================================


class TestRouterNameFromLabel:
    def test_valid_label(self) -> None:
        assert _router_name_from_label("traefik.http.routers.my-rtr.rule=Host(...)") == "my-rtr"

    def test_no_routers_segment(self) -> None:
        assert _router_name_from_label("traefik.http.services.svc.port=80") is None

    def test_routers_at_end_of_parts(self) -> None:
        assert _router_name_from_label("traefik.http.routers") is None


# =============================================================================
# Test: Helper functions — _routers_with_tls_enabled / _routers_with_certresolver
# =============================================================================


class TestRouterHelpers:
    def test_routers_with_tls_enabled(self) -> None:
        labels = [
            "traefik.http.routers.app-rtr.tls=true",
            "traefik.http.routers.other-rtr.rule=Host(`x`)",
        ]
        assert _routers_with_tls_enabled(labels) == {"app-rtr"}

    def test_routers_with_certresolver(self) -> None:
        labels = [
            "traefik.http.routers.app-rtr.tls.certresolver=dns-cf",
            "traefik.http.routers.other-rtr.rule=Host(`x`)",
        ]
        assert _routers_with_certresolver(labels) == {"app-rtr"}


# =============================================================================
# Test: Helper functions — _parse_duration_seconds
# =============================================================================


class TestParseDurationSeconds:
    def test_none_returns_none(self) -> None:
        assert _parse_duration_seconds(None) is None

    def test_int_value(self) -> None:
        assert _parse_duration_seconds(30) == 30

    def test_positive_float(self) -> None:
        assert _parse_duration_seconds(10.5) == 10

    def test_negative_float(self) -> None:
        assert _parse_duration_seconds(-1.0) is None

    def test_non_string_non_numeric(self) -> None:
        assert _parse_duration_seconds([]) is None

    def test_empty_string(self) -> None:
        assert _parse_duration_seconds("") is None
        assert _parse_duration_seconds("  ") is None

    def test_digit_string(self) -> None:
        assert _parse_duration_seconds("30") == 30

    def test_no_matches(self) -> None:
        assert _parse_duration_seconds("abc") is None

    def test_partial_match(self) -> None:
        assert _parse_duration_seconds("10sabc") is None

    def test_compound_duration(self) -> None:
        assert _parse_duration_seconds("1m30s") == 90

    def test_hours(self) -> None:
        assert _parse_duration_seconds("1h") == 3600


# =============================================================================
# Test: Helper functions — _deploy_labels_as_strings
# =============================================================================


class TestDeployLabelsAsStrings:
    def test_returns_labels(self) -> None:
        config = {"deploy": {"labels": ["traefik.enable=true"]}}
        assert _deploy_labels_as_strings(config) == ["traefik.enable=true"]

    def test_no_deploy(self) -> None:
        assert _deploy_labels_as_strings({}) == []


# =============================================================================
# Test: Helper functions — _service_command_strings
# =============================================================================


class TestServiceCommandStrings:
    def test_no_command(self) -> None:
        assert _service_command_strings({}) == []

    def test_list_command(self) -> None:
        assert _service_command_strings({"command": ["a", "b"]}) == ["a", "b"]

    def test_string_command(self) -> None:
        assert _service_command_strings({"command": "single"}) == ["single"]


# =============================================================================
# Test: Helper functions — _deploy_placement_constraints
# =============================================================================


class TestDeployPlacementConstraints:
    def test_no_deploy(self) -> None:
        assert _deploy_placement_constraints({}) == []

    def test_non_dict_deploy(self) -> None:
        assert _deploy_placement_constraints({"deploy": "invalid"}) == []

    def test_non_dict_placement(self) -> None:
        assert _deploy_placement_constraints({"deploy": {"placement": "invalid"}}) == []

    def test_empty_constraints(self) -> None:
        assert _deploy_placement_constraints({"deploy": {"placement": {"constraints": []}}}) == []

    def test_list_constraints(self) -> None:
        result = _deploy_placement_constraints({"deploy": {"placement": {"constraints": ["node.role == manager"]}}})
        assert result == ["node.role == manager"]

    def test_single_string_constraint(self) -> None:
        result = _deploy_placement_constraints({"deploy": {"placement": {"constraints": "node.role == manager"}}})
        assert result == ["node.role == manager"]


# =============================================================================
# Test: Helper functions — _volume_entry_has_docker_socket
# =============================================================================


class TestVolumeEntryHasDockerSocket:
    def test_string_with_socket(self) -> None:
        assert _volume_entry_has_docker_socket("/var/run/docker.sock:/var/run/docker.sock:ro")

    def test_string_without_socket(self) -> None:
        assert not _volume_entry_has_docker_socket("/data:/data")

    def test_dict_source_match(self) -> None:
        assert _volume_entry_has_docker_socket({"source": "/var/run/docker.sock", "target": "/sock"})

    def test_dict_target_match(self) -> None:
        assert _volume_entry_has_docker_socket({"source": "/sock", "target": "/var/run/docker.sock"})

    def test_dict_no_match(self) -> None:
        assert not _volume_entry_has_docker_socket({"source": "/data", "target": "/data"})

    def test_non_string_non_dict(self) -> None:
        assert not _volume_entry_has_docker_socket(12345)


# =============================================================================
# Test: Helper functions — _service_mounts_docker_socket
# =============================================================================


class TestServiceMountsDockerSocket:
    def test_non_list_volumes_returns_false(self) -> None:
        assert not _service_mounts_docker_socket({"volumes": "not-a-list"})

    def test_empty_volumes(self) -> None:
        assert not _service_mounts_docker_socket({"volumes": []})
        assert not _service_mounts_docker_socket({})


# =============================================================================
# Test: Helper functions — _service_network_names
# =============================================================================


class TestServiceNetworkNames:
    def test_no_networks(self) -> None:
        assert _service_network_names({}) == []

    def test_string_network(self) -> None:
        assert _service_network_names({"networks": "mynet"}) == ["mynet"]

    def test_list_networks(self) -> None:
        assert _service_network_names({"networks": ["net1", "net2"]}) == ["net1", "net2"]

    def test_dict_networks(self) -> None:
        assert _service_network_names({"networks": {"net1": {}, "net2": {}}}) == ["net1", "net2"]

    def test_unknown_type_returns_empty(self) -> None:
        assert _service_network_names({"networks": 12345}) == []


# =============================================================================
# Test: Helper functions — _user_is_non_root
# =============================================================================


class TestUserIsNonRoot:
    def test_none_is_root(self) -> None:
        assert not _user_is_non_root(None)

    def test_int_zero_is_root(self) -> None:
        assert not _user_is_non_root(0)

    def test_int_nonzero_is_nonroot(self) -> None:
        assert _user_is_non_root(1000)

    def test_non_string_non_int(self) -> None:
        assert not _user_is_non_root([])

    def test_empty_string_is_root(self) -> None:
        assert not _user_is_non_root("")
        assert not _user_is_non_root("  ")

    def test_root_string(self) -> None:
        assert not _user_is_non_root("root")
        assert not _user_is_non_root("Root")

    def test_zero_colon_zero(self) -> None:
        assert not _user_is_non_root("0:0")

    def test_nonroot_uid(self) -> None:
        assert _user_is_non_root("1000:1000")
        assert _user_is_non_root("65532")


# =============================================================================
# Test: Helper functions — _security_opt_has_no_new_privileges
# =============================================================================


class TestSecurityOptHasNoNewPrivileges:
    def test_has_no_new_privileges(self) -> None:
        assert _security_opt_has_no_new_privileges({"security_opt": ["no-new-privileges:true"]})

    def test_missing_security_opt(self) -> None:
        assert not _security_opt_has_no_new_privileges({})

    def test_non_list_security_opt(self) -> None:
        assert not _security_opt_has_no_new_privileges({"security_opt": "not-a-list"})


# =============================================================================
# Test: Helper functions — OWASP helpers
# =============================================================================


class TestEnvValueLooksLikeLiteralSecret:
    def test_empty_value(self) -> None:
        assert not _env_value_looks_like_literal_secret("")

    def test_variable_substitution(self) -> None:
        assert not _env_value_looks_like_literal_secret("${MY_SECRET}")

    def test_run_secrets_path(self) -> None:
        assert not _env_value_looks_like_literal_secret("/run/secrets/my_secret")

    def test_file_uri_secrets(self) -> None:
        assert not _env_value_looks_like_literal_secret("file:///run/secrets/my_secret")

    def test_literal_value(self) -> None:
        assert _env_value_looks_like_literal_secret("my-secret-value")


class TestExtractImageTag:
    def test_digest_returns_none(self) -> None:
        assert _extract_image_tag("nginx@sha256:abc123") is None

    def test_no_tag_returns_none(self) -> None:
        assert _extract_image_tag("nginx") is None

    def test_with_tag(self) -> None:
        assert _extract_image_tag("nginx:1.27") == "1.27"

    def test_with_registry_and_tag(self) -> None:
        assert _extract_image_tag("ghcr.io/org/image:v1") == "v1"

    def test_no_tag_with_registry(self) -> None:
        assert _extract_image_tag("ghcr.io/org/image") is None


class TestEnvNameLooksSensitive:
    def test_sensitive_names(self) -> None:
        assert _env_name_looks_sensitive("DB_PASSWORD")
        assert _env_name_looks_sensitive("API_KEY")
        assert _env_name_looks_sensitive("AUTH_TOKEN")

    def test_non_sensitive_name(self) -> None:
        assert not _env_name_looks_sensitive("DATABASE_HOST")


class TestReferencesSecretFile:
    def test_empty_value(self) -> None:
        assert not _references_secret_file("")

    def test_file_uri(self) -> None:
        assert _references_secret_file("file:///run/secrets/my_key")

    def test_direct_path(self) -> None:
        assert _references_secret_file("/run/secrets/my_key")

    def test_normal_value(self) -> None:
        assert not _references_secret_file("some-value")


class TestEnvVarNeedsSecretWarning:
    def test_file_suffix_no_warning(self) -> None:
        assert not _env_var_needs_secret_warning("DB_PASSWORD_FILE", "/run/secrets/db")

    def test_references_secret_file_no_warning(self) -> None:
        assert not _env_var_needs_secret_warning("DB_PASSWORD", "/run/secrets/db_pass")

    def test_sensitive_literal_needs_warning(self) -> None:
        assert _env_var_needs_secret_warning("DB_PASSWORD", "hunter2")


# =============================================================================
# Test: _lint_domain_reference_item
# =============================================================================


class TestLintDomainReferenceItem:
    def test_default_fallback_in_label(self) -> None:
        item = "traefik.http.routers.rtr.rule=Host(`app.${DOMAIN_NAME:-example.com}`)"
        results = _lint_domain_reference_item("traefik", item)
        assert any(res.check_id == "TRAEFIK-DOMAIN-001" for res in results)

    def test_hardcoded_host_rule(self) -> None:
        item = "traefik.http.routers.rtr.rule=Host(`app.example.com`)"
        results = _lint_domain_reference_item("traefik", item)
        assert any("hardcode" in res.message.lower() for res in results)

    def test_valid_host_with_var(self) -> None:
        item = "traefik.http.routers.rtr.rule=Host(`app.${DOMAIN_NAME?required}`)"
        results = _lint_domain_reference_item("traefik", item)
        assert len(results) == 0


class TestHasDomainVarDefault:
    def test_with_default(self) -> None:
        assert _has_domain_var_default("${DOMAIN_NAME:-example.com}")

    def test_without_default(self) -> None:
        assert not _has_domain_var_default("${DOMAIN_NAME?required}")


# =============================================================================
# Test: check functions — non-dict services/config skip branches
# =============================================================================


class TestNonDictServicesBranches:
    """Cover skip branches when services or service_config is not a dict."""

    def test_healthcheck_non_dict_services(self) -> None:
        assert check_healthcheck_timing_for_swarm_stacks({"services": "invalid"}) == []

    def test_healthcheck_non_dict_config(self) -> None:
        assert check_healthcheck_timing_for_swarm_stacks({"services": {"app": "invalid"}}) == []

    def test_healthcheck_interval_or_timeout_none(self) -> None:
        compose = {
            "services": {
                "app": {
                    "healthcheck": {
                        "interval": "10s",
                    }
                }
            }
        }
        assert check_healthcheck_timing_for_swarm_stacks(compose) == []

    def test_socket_proxy_non_dict_services(self) -> None:
        assert check_socket_proxy_access_for_swarm_stacks({"services": "invalid"}) == []

    def test_socket_proxy_non_dict_service_config(self) -> None:
        compose = {
            "services": {
                "socket-proxy": {
                    "image": "wollomatic/socket-proxy:1",
                    "deploy": {"placement": {"constraints": ["node.role == manager"]}},
                },
                "traefik": "not-a-dict",
            }
        }
        results = check_socket_proxy_access_for_swarm_stacks(compose)
        assert not any(res.service == "traefik" for res in results)

    def test_docker_socket_non_dict_services(self) -> None:
        assert check_docker_socket_mounts_restricted_for_swarm_stacks({"services": "invalid"}) == []

    def test_docker_socket_non_dict_config(self) -> None:
        compose = {"services": {"app": "invalid"}}
        assert check_docker_socket_mounts_restricted_for_swarm_stacks(compose) == []

    def test_labels_non_dict_config(self) -> None:
        compose = {"services": {"app": "invalid"}}
        assert check_labels_in_deploy_section(compose) == []

    def test_loadbalancer_non_dict_config(self) -> None:
        compose = {"services": {"app": "invalid"}}
        assert check_loadbalancer_port_defined(compose) == []

    def test_docker_network_non_dict_config(self) -> None:
        compose = {"services": {"app": "invalid"}}
        assert check_docker_network_label_for_multi_network_traefik_services(compose) == []

    def test_docker_network_non_dict_deploy(self) -> None:
        compose = {
            "services": {
                "app": {
                    "networks": ["net1", "net2"],
                    "deploy": "invalid",
                }
            }
        }
        assert check_docker_network_label_for_multi_network_traefik_services(compose) == []

    def test_swarm_provider_non_dict_config(self) -> None:
        compose = {"services": {"app": "invalid"}}
        assert check_swarm_provider_not_docker(compose) == []

    def test_network_mode_non_dict_config(self) -> None:
        compose = {"services": {"app": "invalid"}}
        assert check_network_mode_host(compose) == []

    def test_restart_non_dict_config(self) -> None:
        compose = {"services": {"app": "invalid"}}
        assert check_restart_policy_swarm(compose) == []

    def test_owasp_non_dict_services(self) -> None:
        assert check_owasp_docker_baseline_weaknesses({"services": "invalid"}) == []

    def test_owasp_non_dict_config(self) -> None:
        assert check_owasp_docker_baseline_weaknesses({"services": {"app": "invalid"}}) == []

    def test_hardening_non_dict_services(self) -> None:
        assert check_baseline_hardening_for_swarm_stacks({"services": "invalid"}) == []

    def test_hardening_non_dict_config(self) -> None:
        assert check_baseline_hardening_for_swarm_stacks({"services": {"app": "invalid"}}) == []

    def test_security_opt_non_dict_config(self) -> None:
        compose = {"services": {"app": "invalid"}}
        assert check_security_opt_invalid(compose) == []

    def test_invalid_keys_non_dict_config(self) -> None:
        compose = {"services": {"app": "invalid"}}
        assert check_invalid_swarm_keys(compose) == []

    def test_certresolver_non_dict_config(self) -> None:
        compose = {"services": {"app": "invalid"}}
        assert check_certresolver_with_tls(compose) == []

    def test_api_insecure_non_dict_config(self) -> None:
        compose = {"services": {"app": "invalid"}}
        assert check_api_insecure_for_dashboard(compose) == []

    def test_rule_syntax_non_dict_config(self) -> None:
        compose = {"services": {"app": "invalid"}}
        assert check_rule_syntax_deprecated(compose) == []


# =============================================================================
# Test: check_loadbalancer_port_defined — dict labels branch
# =============================================================================


class TestLoadbalancerPortDictLabels:
    def test_dict_labels_missing_port(self) -> None:
        compose = {
            "services": {
                "app": {
                    "image": "nginx:1.27",
                    "deploy": {
                        "labels": {
                            "traefik.enable": "true",
                            "traefik.http.routers.app.rule": "Host(`app.example.com`)",
                        }
                    },
                }
            }
        }
        results = check_loadbalancer_port_defined(compose)
        assert any(res.check_id == "TRAEFIK-PORT-001" for res in results)

    def test_traefik_not_enabled_skipped(self) -> None:
        compose = {
            "services": {
                "app": {
                    "image": "nginx:1.27",
                    "deploy": {
                        "labels": ["traefik.http.routers.app.rule=Host(`app`)"],
                    },
                }
            }
        }
        results = check_loadbalancer_port_defined(compose)
        assert results == []


# =============================================================================
# Test: check_docker_network — labels via _labels_as_kv_strings dict path
# =============================================================================


class TestDockerNetworkDictLabels:
    def test_dict_deploy_labels_with_multi_network(self) -> None:
        compose = {
            "services": {
                "app": {
                    "image": "nginx:1.27",
                    "networks": ["net1", "net2"],
                    "deploy": {
                        "labels": {
                            "traefik.enable": "true",
                        }
                    },
                }
            }
        }
        results = check_docker_network_label_for_multi_network_traefik_services(compose)
        assert any(res.check_id == "TRAEFIK-NETWORK-001" for res in results)

    def test_multi_network_traefik_not_enabled_skipped(self) -> None:
        compose = {
            "services": {
                "app": {
                    "image": "nginx:1.27",
                    "networks": ["net1", "net2"],
                    "deploy": {
                        "labels": ["traefik.http.routers.app.rule=Host(`app`)"],
                    },
                }
            }
        }
        results = check_docker_network_label_for_multi_network_traefik_services(compose)
        assert results == []


# =============================================================================
# Test: check_api_insecure_for_dashboard — INFO branch
# =============================================================================


class TestApiInsecureInfoBranch:
    def test_dashboard_without_insecure_flag_is_info(self) -> None:
        compose = {
            "services": {
                "traefik": {
                    "image": "traefik:v3.6",
                    "command": ["--api.dashboard=true"],
                }
            }
        }
        results = check_api_insecure_for_dashboard(compose)
        assert len(results) == 1
        assert results[0].severity == Severity.INFO
        assert results[0].check_id == "TRAEFIK-API-002"


# =============================================================================
# Test: check_owasp — _check_literal_secret_env_values branches
# =============================================================================


class TestCheckLiteralSecretEnvValues:
    def test_file_suffix_skipped(self) -> None:
        compose = {
            "services": {
                "app": {
                    "image": "nginx:1.27",
                    "environment": {"DB_PASSWORD_FILE": "/run/secrets/db"},
                }
            }
        }
        results = check_owasp_docker_baseline_weaknesses(compose)
        assert not any(res.check_id == "OWASP-DOCKER-SECRETS-001" for res in results)

    def test_non_sensitive_name_skipped(self) -> None:
        compose = {
            "services": {
                "app": {
                    "image": "nginx:1.27",
                    "environment": {"DATABASE_HOST": "db.local"},
                }
            }
        }
        results = check_owasp_docker_baseline_weaknesses(compose)
        assert not any(res.check_id == "OWASP-DOCKER-SECRETS-001" for res in results)

    def test_no_image_skips_pinning_check(self) -> None:
        compose = {"services": {"app": {"environment": {"FOO": "bar"}}}}
        results = check_owasp_docker_baseline_weaknesses(compose)
        assert not any(res.check_id.startswith("OWASP-DOCKER-IMAGE-") for res in results)


# =============================================================================
# Test: lint_compose_file — integration edge cases
# =============================================================================


class TestLintComposeFileEdgeCases:
    def test_yaml_parse_error(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "stacks" / "edge" / "docker-compose.yml"
        bad_file.parent.mkdir(parents=True, exist_ok=True)
        bad_file.write_text("{{invalid yaml")
        results = lint_compose_file(bad_file)
        assert len(results) == 1
        assert results[0].check_id == "YAML-PARSE-001"

    def test_os_error(self, tmp_path: Path) -> None:
        missing_file = tmp_path / "stacks" / "edge" / "docker-compose.yml"
        results = lint_compose_file(missing_file)
        assert len(results) == 1
        assert results[0].check_id == "FILE-READ-001"

    def test_non_dict_compose(self, tmp_path: Path) -> None:
        compose_file = tmp_path / "stacks" / "edge" / "docker-compose.yml"
        compose_file.parent.mkdir(parents=True, exist_ok=True)
        compose_file.write_text("- just a list")
        results = lint_compose_file(compose_file)
        assert results == []

    def test_swarm_stack_no_services_key(self, tmp_path: Path) -> None:
        compose_file = tmp_path / "stacks" / "edge" / "docker-compose.yml"
        compose_file.parent.mkdir(parents=True, exist_ok=True)
        compose_file.write_text(yaml.dump({"networks": {"default": {}}}))
        results = lint_compose_file(compose_file)
        assert results == []


# =============================================================================
# Test: main()
# =============================================================================


class TestMain:
    def test_main_returns_int(self) -> None:
        with patch("sys.argv", ["lint_swarm", "--help"]):
            try:
                main()
            except SystemExit as exc:
                assert exc.code == 0
