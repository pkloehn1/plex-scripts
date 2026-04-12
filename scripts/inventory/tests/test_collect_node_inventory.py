from __future__ import annotations

from pathlib import Path

import yaml

from scripts.inventory.collect_node_inventory import (
    CollectedInventory,
    UpdateResult,
    update_nodes_yml,
)

_FIXTURES = Path(__file__).parent / "fixtures"


def test_update_nodes_yml_preserves_roles_and_notes(tmp_path: Path) -> None:
    nodes_yml = tmp_path / "nodes.yml"
    nodes_yml.write_text(
        (_FIXTURES / "nodes-with-roles-notes.yml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    inv = CollectedInventory(
        hostname="prd-srv-control-01",
        platform="Ubuntu 24.04",
        kernel_release=None,
        network_interfaces=[],
        cpu_model=None,
        cpu_cores=None,
        cpu_threads=None,
        memory_gb=None,
        gpus=[],
        storage=[],
        apt_manual=["htop"],
        snaps=[],
        other=["docker version 27.0.0"],
    )

    result = update_nodes_yml(nodes_yml, inv, dry_run=True)
    assert isinstance(result, UpdateResult)
    parsed = yaml.safe_load(result.rendered)

    node = parsed["nodes"][0]
    assert node["roles"] == ["control"]
    assert node["notes"] == "keep this note"

    # platform updated when collected
    assert node["platform"] == "Ubuntu 24.04"

    # cpu and memory not overwritten when collector didn't find values
    assert node["cpu"]["model"] == "Old CPU"
    assert node["cpu"]["cores"] == 4
    assert node["cpu"]["threads"] == 8
    assert node["memory_gb"] == 16

    # gpus/storage preserved when collector returns empty lists
    assert node["gpus"] == ["manual gpu"]
    assert node["storage"] == ["manual storage"]

    # software lists are treated as collector-owned
    assert node["software"]["apt_manual"] == ["htop"]
    assert node["software"]["snaps"] == []
    assert node["software"]["other"] == ["docker version 27.0.0"]


def test_update_nodes_yml_sorts_nodes_by_hostname(tmp_path: Path) -> None:
    nodes_yml = tmp_path / "nodes.yml"
    nodes_yml.write_text(
        (_FIXTURES / "nodes-unsorted.yml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    inv = CollectedInventory(
        hostname="z-node",
        platform=None,
        kernel_release=None,
        network_interfaces=[],
        cpu_model="CPU",
        cpu_cores=1,
        cpu_threads=1,
        memory_gb=1,
        gpus=[],
        storage=[],
        apt_manual=[],
        snaps=[],
        other=[],
    )

    result = update_nodes_yml(nodes_yml, inv, dry_run=True)
    parsed = yaml.safe_load(result.rendered)
    hostnames = [node["hostname"] for node in parsed["nodes"]]
    assert hostnames == ["a-node", "z-node"]


def test_update_nodes_yml_creates_file_if_missing(tmp_path: Path) -> None:
    nodes_yml = tmp_path / "nodes.yml"
    assert not nodes_yml.exists()

    inv = CollectedInventory(
        hostname="new-node",
        platform="Ubuntu",
        kernel_release=None,
        network_interfaces=[],
        cpu_model="CPU",
        cpu_cores=4,
        cpu_threads=8,
        memory_gb=16,
        gpus=[],
        storage=[],
        apt_manual=[],
        snaps=[],
        other=[],
    )

    result = update_nodes_yml(nodes_yml, inv, dry_run=False)
    assert result.created is True
    assert result.changed is True
    assert result.node_created is True
    assert result.node_changed is True
    assert nodes_yml.exists()


def test_update_nodes_yml_is_idempotent_when_no_delta(tmp_path: Path) -> None:
    nodes_yml = tmp_path / "nodes.yml"

    inv = CollectedInventory(
        hostname="node-a",
        platform="Ubuntu",
        kernel_release=None,
        network_interfaces=[],
        cpu_model="CPU",
        cpu_cores=4,
        cpu_threads=8,
        memory_gb=16,
        gpus=[],
        storage=[],
        apt_manual=[],
        snaps=[],
        other=[],
    )

    first = update_nodes_yml(nodes_yml, inv, dry_run=False)
    second = update_nodes_yml(nodes_yml, inv, dry_run=False)

    assert first.changed is True
    assert second.changed is False
    assert first.node_created is True
    assert second.node_created is False
    assert second.node_changed is False
