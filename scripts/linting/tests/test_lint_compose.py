"""Tests for scripts.linting.lint_compose."""

from __future__ import annotations

from pathlib import Path

from scripts.linting.lint_compose import (
    _is_compose_file,
    _service_labels_as_strings,
    check_baseline_hardening_for_compose,
    check_certresolver_with_tls_compose,
    check_docker_network_label_for_multi_network_traefik_services_compose,
    check_domain_name_not_hardcoded_compose,
    lint_compose_file,
)

# --- _is_compose_file --------------------------------------------------------


class TestIsComposeFile:
    def test_root_docker_compose_yml(self, tmp_path: Path) -> None:
        assert _is_compose_file(tmp_path / "docker-compose.yml") is True

    def test_root_docker_compose_yaml(self, tmp_path: Path) -> None:
        assert _is_compose_file(tmp_path / "docker-compose.yaml") is True

    def test_compose_subdir(self, tmp_path: Path) -> None:
        assert _is_compose_file(tmp_path / "compose" / "traefik" / "docker-compose.yml") is True

    def test_stacks_path_excluded(self, tmp_path: Path) -> None:
        assert _is_compose_file(tmp_path / "stacks" / "edge" / "docker-compose.yml") is False

    def test_stacks_case_insensitive(self, tmp_path: Path) -> None:
        assert _is_compose_file(tmp_path / "Stacks" / "edge" / "docker-compose.yml") is False

    def test_non_compose_filename(self, tmp_path: Path) -> None:
        assert _is_compose_file(tmp_path / "config.yml") is False


# --- _service_labels_as_strings -----------------------------------------------


class TestServiceLabelsAsStrings:
    def test_list_labels(self) -> None:
        config = {"labels": ["traefik.enable=true", "traefik.http.routers.app.rule=Host(`app`)"]}
        result = _service_labels_as_strings(config)
        assert "traefik.enable=true" in result

    def test_missing_labels(self) -> None:
        assert _service_labels_as_strings({}) == []


# --- check_baseline_hardening_for_compose ------------------------------------


class TestBaselineHardeningForCompose:
    def test_missing_cap_drop_all_is_error(self) -> None:
        compose = {
            "services": {
                "app": {
                    "image": "nginx:1.27",
                    "user": "1000:1000",
                    "security_opt": ["no-new-privileges:true"],
                }
            }
        }
        results = check_baseline_hardening_for_compose(compose)
        assert any(item.check_id == "COMPOSE-HARDEN-001" for item in results)

    def test_missing_no_new_privileges_is_error(self) -> None:
        compose = {
            "services": {
                "app": {
                    "image": "nginx:1.27",
                    "user": "1000:1000",
                    "cap_drop": ["ALL"],
                }
            }
        }
        results = check_baseline_hardening_for_compose(compose)
        assert any(item.check_id == "COMPOSE-HARDEN-002" for item in results)

    def test_missing_user_is_error(self) -> None:
        compose = {
            "services": {
                "app": {
                    "image": "nginx:1.27",
                    "cap_drop": ["ALL"],
                    "security_opt": ["no-new-privileges:true"],
                }
            }
        }
        results = check_baseline_hardening_for_compose(compose)
        assert any(item.check_id == "COMPOSE-HARDEN-003" for item in results)

    def test_root_user_is_error(self) -> None:
        compose = {
            "services": {
                "app": {
                    "image": "nginx:1.27",
                    "user": "0:0",
                    "cap_drop": ["ALL"],
                    "security_opt": ["no-new-privileges:true"],
                }
            }
        }
        results = check_baseline_hardening_for_compose(compose)
        assert any(item.check_id == "COMPOSE-HARDEN-003" for item in results)

    def test_allowlisted_root_services_skip_user_check(self) -> None:
        compose = {
            "services": {
                "crowdsec": {
                    "image": "crowdsecurity/crowdsec:v1",
                    "cap_drop": ["ALL"],
                    "security_opt": ["no-new-privileges:true"],
                }
            }
        }
        results = check_baseline_hardening_for_compose(compose)
        assert not any(item.check_id == "COMPOSE-HARDEN-003" for item in results)

    def test_fully_hardened_service_is_valid(self) -> None:
        compose = {
            "services": {
                "app": {
                    "image": "nginx:1.27",
                    "user": "65532:65532",
                    "cap_drop": ["ALL"],
                    "security_opt": ["no-new-privileges:true"],
                }
            }
        }
        results = check_baseline_hardening_for_compose(compose)
        assert results == []

    def test_non_dict_services_returns_empty(self) -> None:
        assert check_baseline_hardening_for_compose({"services": "invalid"}) == []

    def test_non_dict_service_config_skipped(self) -> None:
        compose = {"services": {"app": "not-a-dict"}}
        assert check_baseline_hardening_for_compose(compose) == []

    def test_missing_services_key_returns_empty(self) -> None:
        assert check_baseline_hardening_for_compose({}) == []


# --- check_domain_name_not_hardcoded_compose ---------------------------------


class TestDomainNameNotHardcodedCompose:
    def test_hardcoded_domain_in_labels_is_error(self) -> None:
        compose = {
            "services": {
                "traefik": {
                    "image": "traefik:v3.6",
                    "labels": [
                        "traefik.enable=true",
                        "traefik.http.routers.traefik.rule=Host(`traefik.example.com`)",
                    ],
                }
            }
        }
        results = check_domain_name_not_hardcoded_compose(compose)
        assert any(item.check_id == "TRAEFIK-DOMAIN-001" for item in results)

    def test_non_dict_service_config_skipped(self) -> None:
        compose = {"services": {"app": "not-a-dict"}}
        assert check_domain_name_not_hardcoded_compose(compose) == []

    def test_non_traefik_service_skipped(self) -> None:
        compose = {
            "services": {
                "redis": {
                    "image": "redis:7",
                }
            }
        }
        assert check_domain_name_not_hardcoded_compose(compose) == []


# --- check_docker_network_label_for_multi_network_traefik_services_compose ---


class TestDockerNetworkLabel:
    def test_missing_docker_network_label_is_error(self) -> None:
        compose = {
            "services": {
                "app": {
                    "image": "nginx:1.27",
                    "networks": ["traefik_public", "backend"],
                    "labels": ["traefik.enable=true"],
                }
            }
        }
        results = check_docker_network_label_for_multi_network_traefik_services_compose(compose)
        assert any(item.check_id == "TRAEFIK-NETWORK-001" for item in results)

    def test_wrong_network_value_is_error(self) -> None:
        compose = {
            "services": {
                "app": {
                    "image": "nginx:1.27",
                    "networks": ["traefik_public", "backend"],
                    "labels": [
                        "traefik.enable=true",
                        "traefik.docker.network=nonexistent",
                    ],
                }
            }
        }
        results = check_docker_network_label_for_multi_network_traefik_services_compose(compose)
        assert any(item.check_id == "TRAEFIK-NETWORK-002" for item in results)

    def test_correct_network_label_passes(self) -> None:
        compose = {
            "services": {
                "app": {
                    "image": "nginx:1.27",
                    "networks": ["traefik_public", "backend"],
                    "labels": [
                        "traefik.enable=true",
                        "traefik.docker.network=traefik_public",
                    ],
                }
            }
        }
        results = check_docker_network_label_for_multi_network_traefik_services_compose(compose)
        assert results == []

    def test_single_network_skipped(self) -> None:
        compose = {
            "services": {
                "app": {
                    "image": "nginx:1.27",
                    "networks": ["traefik_public"],
                    "labels": ["traefik.enable=true"],
                }
            }
        }
        results = check_docker_network_label_for_multi_network_traefik_services_compose(compose)
        assert results == []

    def test_non_traefik_multi_network_skipped(self) -> None:
        compose = {
            "services": {
                "app": {
                    "image": "nginx:1.27",
                    "networks": ["frontend", "backend"],
                    "labels": ["traefik.enable=false"],
                }
            }
        }
        results = check_docker_network_label_for_multi_network_traefik_services_compose(compose)
        assert results == []

    def test_non_dict_service_config_skipped(self) -> None:
        compose = {"services": {"app": "not-a-dict"}}
        results = check_docker_network_label_for_multi_network_traefik_services_compose(compose)
        assert results == []

    def test_empty_network_value_is_error(self) -> None:
        compose = {
            "services": {
                "app": {
                    "image": "nginx:1.27",
                    "networks": ["traefik_public", "backend"],
                    "labels": [
                        "traefik.enable=true",
                        "traefik.docker.network=",
                    ],
                }
            }
        }
        results = check_docker_network_label_for_multi_network_traefik_services_compose(compose)
        assert any(item.check_id == "TRAEFIK-NETWORK-002" for item in results)


# --- check_certresolver_with_tls_compose -------------------------------------


class TestCertresolverWithTlsCompose:
    def test_tls_without_certresolver_is_warn(self) -> None:
        compose = {
            "services": {
                "app": {
                    "image": "nginx:1.27",
                    "labels": [
                        "traefik.http.routers.app.tls=true",
                    ],
                }
            }
        }
        results = check_certresolver_with_tls_compose(compose)
        assert any(item.check_id == "TRAEFIK-TLS-001" for item in results)

    def test_tls_with_certresolver_passes(self) -> None:
        compose = {
            "services": {
                "app": {
                    "image": "nginx:1.27",
                    "labels": [
                        "traefik.http.routers.app.tls=true",
                        "traefik.http.routers.app.tls.certresolver=letsencrypt",
                    ],
                }
            }
        }
        results = check_certresolver_with_tls_compose(compose)
        assert results == []

    def test_no_labels_skipped(self) -> None:
        compose = {"services": {"app": {"image": "nginx:1.27"}}}
        results = check_certresolver_with_tls_compose(compose)
        assert results == []

    def test_non_dict_service_config_skipped(self) -> None:
        compose = {"services": {"app": "not-a-dict"}}
        results = check_certresolver_with_tls_compose(compose)
        assert results == []


# --- lint_compose_file -------------------------------------------------------


class TestLintComposeFile:
    def test_skips_stacks_paths(self, tmp_path: Path) -> None:
        compose_file = tmp_path / "stacks" / "edge" / "traefik" / "docker-compose.yml"
        compose_file.parent.mkdir(parents=True, exist_ok=True)
        compose_file.write_text("---\nservices:\n  app:\n    image: nginx:1.27\n", encoding="utf-8")
        assert lint_compose_file(compose_file) == []

    def test_flags_missing_security_opt(self, tmp_path: Path) -> None:
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text(
            '---\nservices:\n  app:\n    image: nginx:1.27\n    user: "1000:1000"\n    cap_drop:\n      - ALL\n',
            encoding="utf-8",
        )
        results = lint_compose_file(compose_file)
        assert any(item.check_id == "COMPOSE-HARDEN-002" for item in results)

    def test_valid_baseline_passes(self, tmp_path: Path) -> None:
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text(
            "---\nservices:\n  app:\n    image: nginx:1.27\n"
            '    user: "1000:1000"\n    cap_drop:\n      - ALL\n'
            "    security_opt:\n      - no-new-privileges:true\n",
            encoding="utf-8",
        )
        assert lint_compose_file(compose_file) == []

    def test_yaml_parse_error(self, tmp_path: Path) -> None:
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text("---\n: :\n  - [invalid\n", encoding="utf-8")
        results = lint_compose_file(compose_file)
        assert any(item.check_id == "YAML-PARSE-001" for item in results)

    def test_file_read_error(self, tmp_path: Path) -> None:
        results = lint_compose_file(tmp_path / "nonexistent" / "docker-compose.yml")
        assert any(item.check_id == "FILE-READ-001" for item in results)

    def test_non_dict_compose_returns_empty(self, tmp_path: Path) -> None:
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text("---\n- item1\n- item2\n", encoding="utf-8")
        assert lint_compose_file(compose_file) == []

    def test_no_services_key_returns_empty(self, tmp_path: Path) -> None:
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text("---\nversion: '3'\n", encoding="utf-8")
        assert lint_compose_file(compose_file) == []
