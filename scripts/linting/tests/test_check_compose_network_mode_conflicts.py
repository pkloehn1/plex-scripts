from __future__ import annotations

from pathlib import Path

import yaml

from scripts.linting.check_compose_network_mode_conflicts import (
    _load_yaml,
    _parse_args,
    check_compose_network_mode_conflicts,
    main,
)


def test_no_services_is_valid(tmp_path: Path) -> None:
    compose = {"networks": {"n": {"external": True}}}
    findings = check_compose_network_mode_conflicts(compose, file_path=tmp_path / "a.yml")
    assert findings == []


def test_service_with_only_networks_is_valid(tmp_path: Path) -> None:
    compose = {"services": {"app": {"image": "nginx:1.27", "networks": ["n"]}}}
    findings = check_compose_network_mode_conflicts(compose, file_path=tmp_path / "a.yml")
    assert findings == []


def test_service_with_only_network_mode_is_valid(tmp_path: Path) -> None:
    compose = {"services": {"app": {"image": "nginx:1.27", "network_mode": "host"}}}
    findings = check_compose_network_mode_conflicts(compose, file_path=tmp_path / "a.yml")
    assert findings == []


def test_service_with_network_mode_and_networks_is_error(tmp_path: Path) -> None:
    compose = {
        "services": {
            "app": {
                "image": "nginx:1.27",
                "network_mode": "host",
                "networks": ["n"],
            }
        }
    }
    findings = check_compose_network_mode_conflicts(compose, file_path=tmp_path / "a.yml")
    assert len(findings) == 1
    assert findings[0].service == "app"
    assert "COMPOSE-NETWORK-001" in findings[0].message


def test_yaml_loader_ignores_commented_network_mode(tmp_path: Path) -> None:
    compose_file = tmp_path / "compose.yml"
    compose_file.write_text(
        """
services:
    app:
        image: nginx:1.27
        # network_mode: host
        networks:
            - n
""",
        encoding="utf-8",
    )

    loaded = yaml.safe_load(compose_file.read_text(encoding="utf-8"))
    findings = check_compose_network_mode_conflicts(loaded, file_path=compose_file)
    assert findings == []


def test_non_dict_service_config_skipped(tmp_path: Path) -> None:
    compose = {"services": {"app": "not-a-dict"}}
    findings = check_compose_network_mode_conflicts(compose, file_path=tmp_path / "a.yml")
    assert findings == []


def test_parse_args_returns_namespace() -> None:
    args = _parse_args(["file1.yml", "file2.yml"])
    assert len(args.files) == 2


def test_load_yaml_valid(tmp_path: Path) -> None:
    compose_file = tmp_path / "compose.yml"
    compose_file.write_text("services:\n  app:\n    image: nginx:1.27\n", encoding="utf-8")
    result = _load_yaml(compose_file)
    assert result is not None
    assert "services" in result


def test_load_yaml_read_error(tmp_path: Path) -> None:
    result = _load_yaml(tmp_path / "missing.yml")
    assert result is None


def test_load_yaml_parse_error(tmp_path: Path) -> None:
    bad_file = tmp_path / "bad.yml"
    bad_file.write_text(":\n  - [invalid", encoding="utf-8")
    result = _load_yaml(bad_file)
    assert result is None


def test_load_yaml_non_dict(tmp_path: Path) -> None:
    list_file = tmp_path / "list.yml"
    list_file.write_text("- item1\n- item2\n", encoding="utf-8")
    result = _load_yaml(list_file)
    assert result == {}


def test_main_no_findings(tmp_path: Path) -> None:
    compose_file = tmp_path / "compose.yml"
    compose_file.write_text("services:\n  app:\n    image: nginx:1.27\n", encoding="utf-8")
    code = main([str(compose_file)])
    assert code == 0


def test_main_with_findings(tmp_path: Path) -> None:
    compose_file = tmp_path / "compose.yml"
    compose_file.write_text(
        "services:\n  app:\n    image: nginx:1.27\n    network_mode: host\n    networks:\n      - n\n",
        encoding="utf-8",
    )
    code = main([str(compose_file)])
    assert code == 1


def test_main_with_bad_yaml(tmp_path: Path) -> None:
    bad_file = tmp_path / "bad.yml"
    bad_file.write_text(":\n  - [invalid", encoding="utf-8")
    code = main([str(bad_file)])
    assert code == 1
