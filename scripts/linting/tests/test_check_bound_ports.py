"""Tests for scripts.linting.check_bound_ports."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

from scripts.linting.check_bound_ports import (
    Finding,
    _find_port_line_number,
    _iter_service_ports,
    _load_compose_yaml,
    _print_violations,
    _validate_input_file,
    check_file,
    check_port_binding,
    main,
    validate_path,
)


class TestCheckPortBinding:
    def test_bound_with_env_var(self) -> None:
        assert check_port_binding("${HOST_IP}:80:80") is True

    def test_bound_with_literal_ip(self) -> None:
        assert check_port_binding("127.0.0.1:80:80") is True

    def test_unbound_port(self) -> None:
        assert check_port_binding("80:80") is False

    def test_container_only_port(self) -> None:
        assert check_port_binding("80") is True

    def test_quoted_bound(self) -> None:
        assert check_port_binding('"${HOST_IP}:8080:80"') is True

    def test_with_protocol(self) -> None:
        assert check_port_binding("${HOST_IP}:53:53/udp") is True

    def test_unbound_with_protocol(self) -> None:
        assert check_port_binding("53:53/udp") is False


class TestLoadComposeYaml:
    def test_valid_yaml(self, tmp_path: Path) -> None:
        compose = tmp_path / "compose.yml"
        compose.write_text("services:\n  app:\n    image: nginx:1.27\n", encoding="utf-8")
        data, lines = _load_compose_yaml(compose)
        assert data is not None
        assert lines is not None
        assert "services" in data

    def test_invalid_yaml(self, tmp_path: Path) -> None:
        compose = tmp_path / "compose.yml"
        compose.write_text(":\n  :\n    - [invalid", encoding="utf-8")
        data, lines = _load_compose_yaml(compose)
        assert data is None
        assert lines is None

    def test_missing_file(self, tmp_path: Path) -> None:
        data, lines = _load_compose_yaml(tmp_path / "missing.yml")
        assert data is None
        assert lines is None

    def test_non_dict_yaml(self, tmp_path: Path) -> None:
        compose = tmp_path / "compose.yml"
        compose.write_text("- item1\n- item2\n", encoding="utf-8")
        data, lines = _load_compose_yaml(compose)
        assert data == {}
        assert lines is not None


class TestIterServicePorts:
    def test_no_services(self) -> None:
        assert list(_iter_service_ports({})) == []

    def test_non_dict_services(self) -> None:
        assert list(_iter_service_ports({"services": "invalid"})) == []

    def test_non_dict_service_config(self) -> None:
        assert list(_iter_service_ports({"services": {"app": "invalid"}})) == []

    def test_no_ports(self) -> None:
        assert list(_iter_service_ports({"services": {"app": {"image": "nginx:1.27"}}})) == []

    def test_with_ports(self) -> None:
        data = {"services": {"app": {"ports": ["80:80", "443:443"]}}}
        result = list(_iter_service_ports(data))
        assert len(result) == 2
        assert result[0] == ("app", "80:80")


class TestFindPortLineNumber:
    def test_finds_line(self) -> None:
        lines = ["services:", "  app:", "    ports:", '      - "80:80"']
        assert _find_port_line_number(lines, "80:80") == 4

    def test_not_found(self) -> None:
        assert _find_port_line_number(["services:"], "80:80") == 0


class TestCheckFile:
    def test_valid_file(self, tmp_path: Path) -> None:
        compose = tmp_path / "compose.yml"
        compose.write_text(
            "services:\n  app:\n    image: nginx:1.27\n    ports:\n      - ${HOST_IP}:80:80\n",
            encoding="utf-8",
        )
        assert check_file(compose) == []

    def test_unbound_port(self, tmp_path: Path) -> None:
        compose = tmp_path / "compose.yml"
        compose.write_text(
            "services:\n  app:\n    image: nginx:1.27\n    ports:\n      - 80:80\n",
            encoding="utf-8",
        )
        findings = check_file(compose)
        assert len(findings) == 1
        assert findings[0].service == "app"

    def test_parse_error(self, tmp_path: Path) -> None:
        compose = tmp_path / "compose.yml"
        compose.write_text(":\n  invalid", encoding="utf-8")
        findings = check_file(compose)
        assert len(findings) == 1
        assert findings[0].service == "FILE_ERROR"

    def test_no_services_key(self, tmp_path: Path) -> None:
        compose = tmp_path / "compose.yml"
        compose.write_text("version: '3'\n", encoding="utf-8")
        assert check_file(compose) == []


class TestValidatePath:
    def test_valid_path(self, tmp_path: Path) -> None:
        target = tmp_path / "file.yml"
        target.write_text("", encoding="utf-8")
        result = validate_path("file.yml", tmp_path)
        assert result is not None

    def test_null_byte(self, tmp_path: Path) -> None:
        assert validate_path("file\x00.yml", tmp_path) is None

    def test_traversal(self, tmp_path: Path) -> None:
        assert validate_path("../../etc/passwd", tmp_path) is None

    def test_valid_nested(self, tmp_path: Path) -> None:
        subdir = tmp_path / "sub"
        subdir.mkdir()
        target = subdir / "file.yml"
        target.write_text("", encoding="utf-8")
        result = validate_path("sub/file.yml", tmp_path)
        assert result is not None


class TestValidateInputFile:
    def test_valid(self, tmp_path: Path) -> None:
        target = tmp_path / "file.yml"
        target.write_text("", encoding="utf-8")
        filepath, error = _validate_input_file("file.yml", tmp_path)
        assert filepath is not None
        assert error is None

    def test_traversal(self, tmp_path: Path) -> None:
        filepath, error = _validate_input_file("../../etc/passwd", tmp_path)
        assert filepath is None
        assert error is not None
        assert "outside allowed directory" in error

    def test_not_found(self, tmp_path: Path) -> None:
        filepath, error = _validate_input_file("missing.yml", tmp_path)
        assert filepath is None
        assert error is not None
        assert "not found" in error


class TestPrintViolations:
    def test_with_line_number(self, capsys: object) -> None:
        findings = [Finding(path=Path("f.yml"), line=5, service="app", port_value="80:80")]
        count = _print_violations(findings)
        assert count == 1
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert "unbound port" in captured.out

    def test_without_line_number(self, capsys: object) -> None:
        findings = [Finding(path=Path("f.yml"), line=-1, service="FILE_ERROR", port_value="error")]
        count = _print_violations(findings)
        assert count == 1
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert "FILE_ERROR" in captured.out


class TestMain:
    def test_no_args(self, capsys: object) -> None:
        with patch.object(sys, "argv", ["check"]):
            code = main()
        assert code == 1

    def test_valid_file(self, tmp_path: Path) -> None:
        compose = tmp_path / "compose.yml"
        compose.write_text(
            "services:\n  app:\n    image: nginx:1.27\n    ports:\n      - ${HOST_IP}:80:80\n",
            encoding="utf-8",
        )
        with patch.object(sys, "argv", ["check", str(compose)]), patch("os.getcwd", return_value=str(tmp_path)):
            code = main()
        assert code == 0

    def test_with_violations(self, tmp_path: Path, capsys: object) -> None:
        compose = tmp_path / "compose.yml"
        compose.write_text(
            "services:\n  app:\n    image: nginx:1.27\n    ports:\n      - 80:80\n",
            encoding="utf-8",
        )
        with patch.object(sys, "argv", ["check", str(compose)]), patch("os.getcwd", return_value=str(tmp_path)):
            code = main()
        assert code == 1
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert "unbound port" in captured.err

    def test_validation_error(self, tmp_path: Path, capsys: object) -> None:
        with patch.object(sys, "argv", ["check", "missing.yml"]), patch("os.getcwd", return_value=str(tmp_path)):
            code = main()
        assert code == 1
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert "not found" in captured.err
