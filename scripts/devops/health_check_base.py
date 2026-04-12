"""Shared base classes for health check scripts.

Provides the common infrastructure used by all DevOps health check scripts:
ANSI color output, local/SSH command execution, and Docker exec wrappers.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from enum import StrEnum

EXIT_OK = 0
EXIT_FAILED = 1


class Color(StrEnum):
    """ANSI color codes for terminal output."""

    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    BLUE = "\033[0;34m"
    RESET = "\033[0m"


@dataclass(frozen=True)
class BaseHealthCheckConfig:
    """Base configuration for health check scripts."""

    edge_node: str
    local_mode: bool
    verbose: bool


class BaseHealthChecker:
    """Base health checker with shared command execution and output methods."""

    def __init__(self, config: BaseHealthCheckConfig) -> None:
        self.config = config

    def run_cmd(self, cmd: str, *, check: bool = True) -> subprocess.CompletedProcess[str]:
        """Run command locally or via SSH based on mode."""
        if self.config.local_mode:
            full_cmd = ["bash", "-c", cmd]
        else:
            full_cmd = ["ssh", self.config.edge_node, cmd]

        if self.config.verbose:
            print(f"{Color.YELLOW.value}> {' '.join(full_cmd)}{Color.RESET.value}")

        return subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            check=check,
        )

    def docker_exec(
        self,
        service_filter: str,
        exec_cmd: str,
        *,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Run command inside a container matched by service filter."""
        container_id = self.run_cmd(
            f"sudo docker ps -q --filter 'name={service_filter}'",
            check=True,
        ).stdout.strip()
        if not container_id:
            raise RuntimeError(f"No container found matching filter: {service_filter}")
        if "\n" in container_id:
            raise RuntimeError(f"Multiple containers match filter '{service_filter}': {container_id.splitlines()}")
        cmd = f"sudo docker exec {container_id} {exec_cmd}"
        return self.run_cmd(cmd, check=check)

    def print_header(self, text: str) -> None:
        """Print section header."""
        print(f"\n{Color.BLUE.value}{'=' * 67}{Color.RESET.value}")
        print(f"{Color.BLUE.value}{text}{Color.RESET.value}")
        print(f"{Color.BLUE.value}{'=' * 67}{Color.RESET.value}")

    def print_success(self, text: str) -> None:
        """Print success message."""
        print(f"{Color.GREEN.value}✓ {text}{Color.RESET.value}")

    def print_warning(self, text: str) -> None:
        """Print warning message."""
        print(f"{Color.YELLOW.value}⚠ {text}{Color.RESET.value}")

    def print_error(self, text: str) -> None:
        """Print error message."""
        print(f"{Color.RED.value}✗ {text}{Color.RESET.value}")
