from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from scripts.inventory._nodes_yml_parsing import normalize_newlines, read_text_if_exists
from scripts.inventory.inventory_types import (
    CollectedInventory,
    HostTarget,
    UpdateResult,
)


class _IndentDumper(yaml.SafeDumper):
    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:  # type: ignore[override]
        super().increase_indent(flow, False)


_NODE_YML_HEADER = """---
# Node capabilities inventory (SSOT)
#
# This file is the single source of truth for hardware/capabilities used for
# service placement planning (Swarm constraints, resource expectations, etc.).
#
# Generated view: docs/inventory/nodes.md
# Generator: scripts/inventory/generate_nodes_docs.py

"""


def _set_if_different(mapping: dict[str, Any], key: str, value: Any) -> bool:
    if mapping.get(key) == value:
        return False
    mapping[key] = value
    return True


def _set_list_if_different(mapping: dict[str, Any], key: str, values: list[Any]) -> bool:
    existing = mapping.get(key)
    if existing == values:
        return False
    mapping[key] = values
    return True


def _ensure_mapping(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if isinstance(value, dict):
        return value
    new_value: dict[str, Any] = {}
    parent[key] = new_value
    return new_value


def _apply_inventory_to_node(node: dict[str, Any], inv: CollectedInventory) -> bool:
    changed = False

    if inv.platform is not None:
        changed |= _set_if_different(node, "platform", inv.platform)

    if inv.kernel_release is not None:
        changed |= _set_if_different(node, "kernel", inv.kernel_release)

    network = _ensure_mapping(node, "network")
    rendered_interfaces = [{"name": iface.name, "addresses": iface.addresses} for iface in inv.network_interfaces]
    if rendered_interfaces or not network.get("interfaces"):
        changed |= _set_list_if_different(network, "interfaces", rendered_interfaces)

    cpu = _ensure_mapping(node, "cpu")
    if inv.cpu_model is not None:
        changed |= _set_if_different(cpu, "model", inv.cpu_model)
    if inv.cpu_cores is not None:
        changed |= _set_if_different(cpu, "cores", inv.cpu_cores)
    if inv.cpu_threads is not None:
        changed |= _set_if_different(cpu, "threads", inv.cpu_threads)

    if inv.memory_gb is not None:
        changed |= _set_if_different(node, "memory_gb", inv.memory_gb)

    if inv.gpus or not node.get("gpus"):
        changed |= _set_list_if_different(node, "gpus", inv.gpus)
    if inv.storage or not node.get("storage"):
        changed |= _set_list_if_different(node, "storage", inv.storage)

    software = _ensure_mapping(node, "software")
    changed |= _set_list_if_different(software, "apt_manual", inv.apt_manual)
    changed |= _set_list_if_different(software, "snaps", inv.snaps)
    changed |= _set_list_if_different(software, "other", inv.other)

    return changed


def _load_nodes_yml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "nodes": []}

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("nodes.yml must be a mapping")
    return raw


def _find_or_create_node(nodes: list[dict[str, Any]], hostname: str) -> dict[str, Any]:
    for node in nodes:
        if node.get("hostname") == hostname:
            return node

    new_node: dict[str, Any] = {
        "hostname": hostname,
        "roles": [],
        "platform": "unknown",
        "kernel": None,
        "network": {"interfaces": []},
        "cpu": {"model": None, "cores": None, "threads": None},
        "memory_gb": None,
        "gpus": [],
        "storage": [],
        "software": {"apt_manual": [], "snaps": [], "other": []},
        "status": "active",
        "notes": None,
    }
    nodes.append(new_node)
    return new_node


def update_nodes_yml(nodes_yml_path: Path, inv: CollectedInventory, *, dry_run: bool) -> UpdateResult:
    existing_text = read_text_if_exists(nodes_yml_path)
    created = existing_text is None

    raw = _load_nodes_yml(nodes_yml_path)

    nodes = raw.get("nodes")
    if not isinstance(nodes, list):
        raise ValueError("nodes.yml must define a 'nodes' list")

    node_created = not any(node.get("hostname") == inv.hostname for node in nodes)
    node = _find_or_create_node(nodes, inv.hostname)

    node_changed = _apply_inventory_to_node(node, inv) or node_created
    changed = node_changed

    nodes_sorted = sorted(nodes, key=lambda node: str(node.get("hostname", "")))
    if nodes != nodes_sorted:
        raw["nodes"] = nodes_sorted
        changed = True

    rendered = _NODE_YML_HEADER + yaml.dump(
        raw,
        Dumper=_IndentDumper,
        sort_keys=False,
        default_flow_style=False,
        indent=2,
    )

    rendered_normalized = normalize_newlines(rendered)
    existing_normalized = normalize_newlines(existing_text) if existing_text else None
    content_changed = created or changed or existing_normalized != rendered_normalized

    if not dry_run and content_changed:
        nodes_yml_path.parent.mkdir(parents=True, exist_ok=True)
        nodes_yml_path.write_text(rendered, encoding="utf-8")

    return UpdateResult(
        rendered=rendered,
        changed=content_changed,
        created=created,
        node_created=node_created,
        node_changed=node_changed,
    )


def _resolve_node_ssh_user(node: dict[str, Any], *, default_user: str) -> str:
    user = node.get("ssh_user")
    if isinstance(user, str) and user.strip():
        return user.strip()

    ssh = node.get("ssh")
    if isinstance(ssh, dict):
        ssh_user = ssh.get("user")
        if isinstance(ssh_user, str) and ssh_user.strip():
            return ssh_user.strip()

    return default_user


def host_targets_from_nodes_yml(nodes_yml_path: Path, *, default_user: str) -> list[HostTarget]:
    raw = _load_nodes_yml(nodes_yml_path)
    nodes = raw.get("nodes")
    if not isinstance(nodes, list):
        raise ValueError("nodes.yml must define a 'nodes' list")

    targets: list[HostTarget] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        hostname = node.get("hostname")
        if not isinstance(hostname, str) or not hostname.strip():
            continue

        user = _resolve_node_ssh_user(node, default_user=default_user)
        targets.append(HostTarget(hostname=hostname.strip(), user=user))

    # Sort + dedupe by hostname (keep first user encountered).
    deduped: dict[str, HostTarget] = {}
    for target in sorted(targets, key=lambda tgt: tgt.hostname):
        deduped.setdefault(target.hostname, target)
    return list(deduped.values())
