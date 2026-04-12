from __future__ import annotations

from pathlib import Path

import pytest

from scripts.inventory.inventory_types import CollectedInventory
from scripts.inventory.nodes_yml import (
    _resolve_node_ssh_user,
    host_targets_from_nodes_yml,
    update_nodes_yml,
)


def _minimal_inv(hostname: str = "node-a") -> CollectedInventory:
    return CollectedInventory(
        hostname=hostname,
        platform=None,
        kernel_release=None,
        network_interfaces=[],
        cpu_model=None,
        cpu_cores=None,
        cpu_threads=None,
        memory_gb=None,
        gpus=[],
        storage=[],
        apt_manual=[],
        snaps=[],
        other=[],
    )


def test_load_nodes_yml_raises_when_content_is_not_mapping(tmp_path: Path) -> None:
    bad_yml = tmp_path / "nodes.yml"
    bad_yml.write_text("- just a list\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"nodes\.yml must be a mapping"):
        update_nodes_yml(bad_yml, _minimal_inv(), dry_run=True)


def test_update_nodes_yml_raises_when_nodes_is_not_list(tmp_path: Path) -> None:
    bad_yml = tmp_path / "nodes.yml"
    bad_yml.write_text("version: 1\nnodes: not-a-list\n", encoding="utf-8")

    with pytest.raises(ValueError, match="'nodes' list"):
        update_nodes_yml(bad_yml, _minimal_inv(), dry_run=True)


def test_resolve_node_ssh_user_uses_ssh_user_field() -> None:
    node = {"hostname": "myhost", "ssh_user": "custom-user"}
    result = _resolve_node_ssh_user(node, default_user="default")
    assert result == "custom-user"


def test_resolve_node_ssh_user_uses_ssh_dict() -> None:
    node = {"hostname": "myhost", "ssh": {"user": "ssh-dict-user"}}
    result = _resolve_node_ssh_user(node, default_user="default")
    assert result == "ssh-dict-user"


def test_resolve_node_ssh_user_falls_back_to_default() -> None:
    node = {"hostname": "myhost"}
    result = _resolve_node_ssh_user(node, default_user="default")
    assert result == "default"


def test_host_targets_raises_when_nodes_not_list(tmp_path: Path) -> None:
    bad_yml = tmp_path / "nodes.yml"
    bad_yml.write_text("version: 1\nnodes: bad\n", encoding="utf-8")

    with pytest.raises(ValueError, match="'nodes' list"):
        host_targets_from_nodes_yml(bad_yml, default_user="root")


def test_host_targets_skips_non_dict_and_missing_hostname(tmp_path: Path) -> None:
    yml = tmp_path / "nodes.yml"
    yml.write_text(
        'version: 1\nnodes:\n  - just-a-string\n  - hostname: ""\n  - hostname: valid-host\n',
        encoding="utf-8",
    )

    targets = host_targets_from_nodes_yml(yml, default_user="root")
    assert len(targets) == 1
    assert targets[0].hostname == "valid-host"
