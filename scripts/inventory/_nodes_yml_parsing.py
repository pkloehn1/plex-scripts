from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ValidatedInterface:
    """A validated network interface with name and addresses."""

    name: str
    addresses: list[str]


@dataclass(frozen=True, slots=True)
class ParsedNodeBase:
    """Common fields shared by all node inventory representations."""

    hostname: str
    roles: list[str]
    platform: str | None
    kernel_release: str | None
    cpu_model: str | None
    cpu_cores: int | None
    cpu_threads: int | None
    memory_gb: int | None
    gpus: list[str]
    software_apt_manual: list[str]
    software_snaps: list[str]
    software_other: list[str]
    status: str | None
    notes: str | None


def read_text_if_exists(path: Path) -> str | None:
    """Read text from *path* if it exists, otherwise return ``None``."""
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def normalize_newlines(text: str) -> str:
    r"""Normalize all line endings to ``\n``."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def optional_str(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Expected string or null")
    value = value.strip()
    return value or None


def optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("Expected int or null")
    if isinstance(value, int):
        return value
    raise ValueError("Expected int or null")


def parse_str_list(mapping: dict[str, object], hostname: str, field_name: str) -> list[str]:
    value = mapping.get(field_name)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"Node {hostname!r} {field_name} must be a list of strings")
    return [item.strip() for item in value if item.strip()]


def require_str_field(mapping: dict[str, object], field_name: str) -> str:
    value = mapping.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Each node must define a non-empty {field_name!r}")
    return value.strip()


def validate_network_interfaces(hostname: str, node: dict[str, object]) -> list[ValidatedInterface]:
    """Validate and extract network interfaces from a node mapping."""
    network_raw = node.get("network") or {}
    if not isinstance(network_raw, dict):
        raise ValueError(f"Node {hostname!r} network must be a mapping")

    interfaces_raw = network_raw.get("interfaces")
    if interfaces_raw is None:
        return []

    if not isinstance(interfaces_raw, list):
        raise ValueError(f"Node {hostname!r} network.interfaces must be a list")

    result: list[ValidatedInterface] = []
    for iface in interfaces_raw:
        if not isinstance(iface, dict):
            raise ValueError(f"Node {hostname!r} network.interfaces entries must be mappings")
        name = iface.get("name")
        addrs = iface.get("addresses")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Node {hostname!r} network.interfaces.name must be a non-empty string")
        if not isinstance(addrs, list) or not all(isinstance(addr, str) for addr in addrs):
            raise ValueError(f"Node {hostname!r} network.interfaces.addresses must be a list of strings")
        cleaned = sorted({addr.strip() for addr in addrs if addr.strip()})
        if cleaned:
            result.append(ValidatedInterface(name=name.strip(), addresses=cleaned))

    result.sort(key=lambda iface: iface.name)
    return result


def parse_node_base_fields(node: object) -> tuple[ParsedNodeBase, list[ValidatedInterface]]:
    """Parse a raw node mapping into base fields and validated interfaces.

    Returns the parsed base fields and the validated network interfaces
    separately, since consumers render interfaces in different formats.
    """
    if not isinstance(node, dict):
        raise ValueError("Each node entry must be a mapping")

    hostname = require_str_field(node, "hostname")
    roles = parse_str_list(node, hostname, "roles")

    cpu_raw = node.get("cpu") or {}
    if not isinstance(cpu_raw, dict):
        raise ValueError(f"Node {hostname!r} cpu must be a mapping")

    software_raw = node.get("software") or {}
    if not isinstance(software_raw, dict):
        raise ValueError(f"Node {hostname!r} software must be a mapping")

    interfaces = validate_network_interfaces(hostname, node)

    base = ParsedNodeBase(
        hostname=hostname,
        roles=roles,
        platform=optional_str(node.get("platform")),
        kernel_release=optional_str(node.get("kernel")),
        cpu_model=optional_str(cpu_raw.get("model")),
        cpu_cores=optional_int(cpu_raw.get("cores")),
        cpu_threads=optional_int(cpu_raw.get("threads")),
        memory_gb=optional_int(node.get("memory_gb")),
        gpus=parse_str_list(node, hostname, "gpus"),
        software_apt_manual=parse_str_list(software_raw, hostname, "apt_manual"),
        software_snaps=parse_str_list(software_raw, hostname, "snaps"),
        software_other=parse_str_list(software_raw, hostname, "other"),
        status=optional_str(node.get("status")),
        notes=optional_str(node.get("notes")),
    )
    return base, interfaces
