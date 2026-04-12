#!/usr/bin/env python3
"""Check that Docker Compose port bindings include an interface.

This script validates that all port mappings in Docker Compose files
bind to a specific interface using either:
- ${HOST_IP} environment variable (preferred)
- Literal IP address (e.g., 127.0.0.1, 192.168.1.1)

Unbound ports (e.g., "80:80" or "8080:8080") are flagged as errors
because they listen on all interfaces (0.0.0.0), which is a security risk.

Exit codes:
    0: All ports are properly bound
    1: Unbound ports found or file parsing error
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# Pattern for valid bound port formats:
# - ${HOST_IP}:port:port or "${HOST_IP}:port:port"
# - 127.0.0.1:port:port or "127.0.0.1:port:port"
# - Any IP:port:port format
BOUND_PORT_PATTERN = re.compile(
    r"^[\"']?"  # Optional opening quote
    r"(\$\{[A-Z_]+\}|"  # Environment variable like ${HOST_IP}
    r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"  # Or literal IP address
    r":\d+:\d+"  # :host_port:container_port
    r"(/udp|/tcp)?"  # Optional protocol
    r"[\"']?$"  # Optional closing quote
)

# Pattern for short syntax ports that need checking
# Matches: "80:80", "8080:8080", 80:80, etc.
UNBOUND_PORT_PATTERN = re.compile(
    r"^[\"']?"  # Optional opening quote
    r"\d+:\d+"  # port:port without interface
    r"(/udp|/tcp)?"  # Optional protocol
    r"[\"']?$"  # Optional closing quote
)


@dataclass(frozen=True)
class Finding:
    """A bound-port violation finding."""

    path: Path
    line: int
    service: str
    port_value: str


def check_port_binding(port_value: str) -> bool:
    """Check if a port binding includes an interface.

    Args:
        port_value: Port mapping string (e.g., "${HOST_IP}:80:80" or "80:80")

    Returns:
        True if port is properly bound to an interface, False otherwise
    """
    port_str = str(port_value).strip()

    # Check if it matches bound pattern (has interface)
    if BOUND_PORT_PATTERN.match(port_str):
        return True

    # Check if it matches unbound pattern (missing interface)
    # Return False if unbound, True otherwise
    return not UNBOUND_PORT_PATTERN.match(port_str)


def _load_compose_yaml(
    filepath: Path,
) -> tuple[dict[str, Any] | None, list[str] | None]:
    try:
        content = filepath.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        print(f"Error parsing {filepath}: {exc}", file=sys.stderr)
        return None, None
    except OSError as exc:
        print(f"Error reading {filepath}: {exc}", file=sys.stderr)
        return None, None

    if not isinstance(data, dict):
        return {}, content.splitlines()

    return data, content.splitlines()


def _iter_service_ports(data: dict[str, Any]) -> Iterator[tuple[str, str]]:
    services = data.get("services")
    if not isinstance(services, dict):
        return

    for service_name, service_config in services.items():
        if not isinstance(service_config, dict):
            continue

        ports = service_config.get("ports")
        if not ports:
            continue

        for port in ports:
            yield str(service_name), str(port)


def _find_port_line_number(lines: list[str], port_str: str) -> int:
    needle = port_str.strip().strip("\"'")
    for idx, line in enumerate(lines, 1):
        if port_str in line or (needle and needle in line):
            return idx
    return 0


def check_file(filepath: Path) -> list[Finding]:
    """Check a Docker Compose file for unbound ports.

    Returns a list of :class:`Finding` instances for each violation.
    """
    violations: list[Finding] = []

    data, lines = _load_compose_yaml(filepath)
    if data is None or lines is None:
        return [Finding(path=filepath, line=-1, service="FILE_ERROR", port_value="Failed to read/parse file")]
    if "services" not in data:
        return violations

    for service_name, port_str in _iter_service_ports(data):
        if check_port_binding(port_str):
            continue
        line_num = _find_port_line_number(lines, port_str)
        violations.append(Finding(path=filepath, line=line_num, service=service_name, port_value=port_str))

    return violations


def validate_path(filepath_str: str, base_dir: Path) -> Path | None:
    """Validate and sanitize file path to prevent path traversal (CWE-22).

    Args:
        filepath_str: User-provided file path string.
        base_dir: Base directory that paths must be within.

    Returns:
        Resolved Path if valid, None if path traversal detected.

    Security:
        OWASP-compliant path traversal prevention:
        1. Reject null bytes (common path traversal attack vector)
        2. Use joinpath() to safely combine base_dir with user input
        3. Use resolve() to normalize path (handles .., symlinks)
        4. Use relative_to() to verify path stays within allowed directory

    Reference:
        - OWASP Input Validation Cheat Sheet
        - https://stackoverflow.com/questions/45188708
    """
    # Reject null bytes (path traversal attack vector per OWASP)
    if "\x00" in filepath_str:
        return None

    try:
        # Resolve base directory to absolute path first
        resolved_base = base_dir.resolve()
        # Use joinpath() to safely combine paths, then resolve
        # This is the OWASP-recommended pattern for path traversal prevention
        filepath = resolved_base.joinpath(filepath_str).resolve()
        # Verify the resolved path is within the allowed base directory
        # relative_to() raises ValueError if filepath is not under resolved_base
        filepath.relative_to(resolved_base)
        return filepath
    except (ValueError, OSError):
        # ValueError: path is outside base directory (path traversal attempt)
        # OSError: invalid path characters or filesystem error
        return None


def _validate_input_file(filepath_str: str, base_dir: Path) -> tuple[Path | None, str | None]:
    filepath = validate_path(filepath_str, base_dir)
    if filepath is None:
        return (
            None,
            f"Security error: Path '{filepath_str}' is outside allowed directory",
        )

    if not filepath.exists():
        return None, f"File not found: {filepath}"

    return filepath, None


def _print_violations(violations: list[Finding]) -> int:
    count = 0
    for finding in violations:
        count += 1
        if finding.line > 0:
            err_prefix = f"{finding.path}:{finding.line} error:"
            err_detail = f"Service '{finding.service}' has unbound port '{finding.port_value}'."
            err_hint = "Use ${HOST_IP}:port:port format."
            print(f"{err_prefix} {err_detail} {err_hint}")
        else:
            print(f"{finding.path} error: {finding.service}: {finding.port_value}")
    return count


def main() -> int:
    """Main entry point."""
    if len(sys.argv) < 2:
        print(
            "Usage: check-bound-ports.py <file1.yml> [file2.yml ...]",
            file=sys.stderr,
        )
        return 1

    # Use current working directory as security boundary
    base_dir = Path.cwd().resolve()

    exit_code = 0
    total_violations = 0

    for filepath_str in sys.argv[1:]:
        filepath, error = _validate_input_file(filepath_str, base_dir)
        if error is not None:
            print(error, file=sys.stderr)
            exit_code = 1
            continue

        assert filepath is not None

        violations = check_file(filepath)
        if not violations:
            continue

        exit_code = 1
        total_violations += _print_violations(violations)

    if total_violations > 0:
        err_count = f"\n✖ {total_violations} unbound port(s) found."
        err_fix = "Bind to ${HOST_IP} or a specific IP address."
        print(f"{err_count} {err_fix}", file=sys.stderr)

    return exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
