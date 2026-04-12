"""Tests for health check base module."""

from __future__ import annotations

import subprocess
from typing import Any
from unittest.mock import MagicMock

import pytest

from scripts.devops.health_check_base import (
    EXIT_FAILED,
    EXIT_OK,
    BaseHealthCheckConfig,
    BaseHealthChecker,
    Color,
)


@pytest.fixture
def local_config() -> BaseHealthCheckConfig:
    """Create a local mode configuration for testing."""
    return BaseHealthCheckConfig(
        edge_node="prd-srv-edge-01",
        local_mode=True,
        verbose=False,
    )


@pytest.fixture
def remote_config() -> BaseHealthCheckConfig:
    """Create a remote mode configuration for testing."""
    return BaseHealthCheckConfig(
        edge_node="prd-srv-edge-01",
        local_mode=False,
        verbose=False,
    )


@pytest.fixture
def checker_local(local_config: BaseHealthCheckConfig) -> BaseHealthChecker:
    """Create a BaseHealthChecker instance in local mode."""
    return BaseHealthChecker(local_config)


@pytest.fixture
def checker_remote(remote_config: BaseHealthCheckConfig) -> BaseHealthChecker:
    """Create a BaseHealthChecker instance in remote mode."""
    return BaseHealthChecker(remote_config)


def test_exit_codes() -> None:
    """Test exit code constants."""
    assert EXIT_OK == 0
    assert EXIT_FAILED == 1


def test_color_enum() -> None:
    """Test Color enum values."""
    assert Color.RED.value == "\033[0;31m"
    assert Color.GREEN.value == "\033[0;32m"
    assert Color.YELLOW.value == "\033[1;33m"
    assert Color.BLUE.value == "\033[0;34m"
    assert Color.RESET.value == "\033[0m"


def test_base_config_creation() -> None:
    """Test BaseHealthCheckConfig creation."""
    config = BaseHealthCheckConfig(
        edge_node="test-node",
        local_mode=True,
        verbose=True,
    )
    assert config.edge_node == "test-node"
    assert config.local_mode is True
    assert config.verbose is True


def test_base_config_frozen() -> None:
    """Test BaseHealthCheckConfig is frozen."""
    config = BaseHealthCheckConfig(
        edge_node="test-node",
        local_mode=True,
        verbose=False,
    )
    with pytest.raises(AttributeError):
        config.edge_node = "other"  # type: ignore[misc]


def test_run_cmd_local_mode(
    checker_local: BaseHealthChecker,
    monkeypatch: Any,
) -> None:
    """Test run_cmd in local mode constructs correct bash command."""
    mock_result = MagicMock(spec=subprocess.CompletedProcess)
    mock_result.stdout = "test output"
    mock_result.returncode = 0

    captured_args: list[list[str]] = []

    def mock_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        captured_args.append(args[0])
        return mock_result

    monkeypatch.setattr(subprocess, "run", mock_run)

    result = checker_local.run_cmd("echo test")

    assert len(captured_args) == 1
    assert captured_args[0] == ["bash", "-c", "echo test"]
    assert result.stdout == "test output"


def test_run_cmd_remote_mode(
    checker_remote: BaseHealthChecker,
    monkeypatch: Any,
) -> None:
    """Test run_cmd in remote mode constructs SSH command."""
    mock_result = MagicMock(spec=subprocess.CompletedProcess)
    mock_result.stdout = "test output"
    mock_result.returncode = 0

    captured_args: list[list[str]] = []

    def mock_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        captured_args.append(args[0])
        return mock_result

    monkeypatch.setattr(subprocess, "run", mock_run)

    result = checker_remote.run_cmd("echo test")

    assert len(captured_args) == 1
    assert captured_args[0] == ["ssh", "prd-srv-edge-01", "echo test"]
    assert result.stdout == "test output"


def test_verbose_mode_shows_commands(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    """Test that verbose mode prints executed commands."""
    verbose_config = BaseHealthCheckConfig(
        edge_node="test-node",
        local_mode=True,
        verbose=True,
    )
    checker = BaseHealthChecker(verbose_config)

    mock_result = MagicMock(spec=subprocess.CompletedProcess)
    mock_result.stdout = "output"
    mock_result.returncode = 0

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_result)

    checker.run_cmd("test command")

    captured = capsys.readouterr()
    assert "> " in captured.out
    assert "bash" in captured.out or "test command" in captured.out


def test_docker_exec_construction(
    checker_local: BaseHealthChecker,
    monkeypatch: Any,
) -> None:
    """Test docker_exec constructs proper docker exec command."""
    call_count = 0

    def mock_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        nonlocal call_count
        call_count += 1
        result = MagicMock(spec=subprocess.CompletedProcess)
        result.returncode = 0
        if call_count == 1:
            result.stdout = "abc123container"
        else:
            result.stdout = "exec output"
        return result

    monkeypatch.setattr(subprocess, "run", mock_run)

    result = checker_local.docker_exec("my_service", "curl -sf http://localhost:8080")

    assert call_count == 2
    assert result.stdout == "exec output"


def test_docker_exec_no_container(
    checker_local: BaseHealthChecker,
    monkeypatch: Any,
) -> None:
    """Test docker_exec raises when no container matches."""
    mock_result = MagicMock(spec=subprocess.CompletedProcess)
    mock_result.stdout = ""
    mock_result.returncode = 0

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_result)

    with pytest.raises(RuntimeError, match="No container found"):
        checker_local.docker_exec("missing_service", "echo test")


def test_docker_exec_multiple_containers(
    checker_local: BaseHealthChecker,
    monkeypatch: Any,
) -> None:
    """Test docker_exec raises when multiple containers match."""
    mock_result = MagicMock(spec=subprocess.CompletedProcess)
    mock_result.stdout = "container1\ncontainer2"
    mock_result.returncode = 0

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: mock_result)

    with pytest.raises(RuntimeError, match="Multiple containers"):
        checker_local.docker_exec("ambiguous_service", "echo test")


def test_print_header(
    checker_local: BaseHealthChecker,
    capsys: Any,
) -> None:
    """Test print_header outputs section header."""
    checker_local.print_header("Test Header")

    captured = capsys.readouterr()
    assert "Test Header" in captured.out
    assert "=" * 67 in captured.out


def test_print_success(
    checker_local: BaseHealthChecker,
    capsys: Any,
) -> None:
    """Test print_success outputs success message."""
    checker_local.print_success("success msg")

    captured = capsys.readouterr()
    assert "✓" in captured.out
    assert "success msg" in captured.out


def test_print_warning(
    checker_local: BaseHealthChecker,
    capsys: Any,
) -> None:
    """Test print_warning outputs warning message."""
    checker_local.print_warning("warning msg")

    captured = capsys.readouterr()
    assert "⚠" in captured.out
    assert "warning msg" in captured.out


def test_print_error(
    checker_local: BaseHealthChecker,
    capsys: Any,
) -> None:
    """Test print_error outputs error message."""
    checker_local.print_error("error msg")

    captured = capsys.readouterr()
    assert "✗" in captured.out
    assert "error msg" in captured.out
