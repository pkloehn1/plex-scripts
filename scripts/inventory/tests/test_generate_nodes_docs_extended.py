from __future__ import annotations

from pathlib import Path

import pytest

from scripts.inventory.generate_nodes_docs import (
    NodeRecord,
    _cpu_summary,
    _load_nodes,
    _normalize_storage,
    _render_storage_dict,
    _render_storage_item,
    _software_summary,
)


def _make_node(**kwargs) -> NodeRecord:
    defaults: dict = {
        "hostname": "test-host",
        "roles": [],
        "platform": None,
        "kernel_release": None,
        "network_interfaces": [],
        "cpu_model": None,
        "cpu_cores": None,
        "cpu_threads": None,
        "memory_gb": None,
        "gpus": [],
        "storage": [],
        "software_apt_manual": [],
        "software_snaps": [],
        "software_other": [],
        "status": None,
        "notes": None,
    }
    defaults.update(kwargs)
    return NodeRecord(**defaults)


# ── _cpu_summary ──────────────────────────────────────────────────────────────


def test_cpu_summary_model_only() -> None:
    node = _make_node(cpu_model="Intel Xeon")
    assert _cpu_summary(node) == "Intel Xeon"


def test_cpu_summary_cores_and_threads() -> None:
    node = _make_node(cpu_cores=4, cpu_threads=8)
    assert "4C/8T" in _cpu_summary(node)


def test_cpu_summary_cores_only() -> None:
    node = _make_node(cpu_cores=4)
    result = _cpu_summary(node)
    assert "4C" in result
    assert "T" not in result


def test_cpu_summary_threads_only() -> None:
    node = _make_node(cpu_threads=8)
    result = _cpu_summary(node)
    assert "8T" in result
    assert "C/" not in result


def test_cpu_summary_all_none_returns_tbd() -> None:
    node = _make_node()
    assert _cpu_summary(node) == "TBD"


# ── _load_nodes raises ────────────────────────────────────────────────────────


def test_load_nodes_raises_when_not_mapping(tmp_path: Path) -> None:
    yml = tmp_path / "nodes.yml"
    yml.write_text("- just a list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a mapping"):
        _load_nodes(yml)


def test_load_nodes_raises_when_nodes_not_list(tmp_path: Path) -> None:
    yml = tmp_path / "nodes.yml"
    yml.write_text("version: 1\nnodes: not-a-list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="'nodes' list"):
        _load_nodes(yml)


# ── _normalize_storage ────────────────────────────────────────────────────────


def test_normalize_storage_raises_on_non_list() -> None:
    with pytest.raises(ValueError, match="storage must be a list"):
        _normalize_storage("bad")


def test_normalize_storage_none_returns_empty() -> None:
    assert _normalize_storage(None) == []


def test_normalize_storage_skips_empty_string_items() -> None:
    result = _normalize_storage(["  ", "ssd"])
    assert result == ["ssd"]


def test_normalize_storage_skips_none_items() -> None:
    result = _normalize_storage([None, "ssd"])
    assert result == ["ssd"]


# ── _render_storage_item ──────────────────────────────────────────────────────


def test_render_storage_item_none_returns_none() -> None:
    assert _render_storage_item(None) is None


def test_render_storage_item_empty_string_returns_none() -> None:
    assert _render_storage_item("   ") is None


def test_render_storage_item_non_str_non_dict_raises() -> None:
    with pytest.raises(ValueError, match="strings or mappings"):
        _render_storage_item(42)


def test_render_storage_item_dict_delegates() -> None:
    result = _render_storage_item({"type": "nvme", "size_gb": 512})
    assert result == "nvme 512GB"


# ── _render_storage_dict ──────────────────────────────────────────────────────


def test_render_storage_dict_raises_on_non_int_size() -> None:
    with pytest.raises(ValueError, match="size_gb must be int or null"):
        _render_storage_dict({"size_gb": "512"})


def test_render_storage_dict_raises_on_non_str_notes() -> None:
    with pytest.raises(ValueError, match="notes must be string or null"):
        _render_storage_dict({"notes": 42})


def test_render_storage_dict_full() -> None:
    result = _render_storage_dict({"type": "nvme", "size_gb": 512, "notes": "OS disk"})
    assert result == "nvme 512GB OS disk"


def test_render_storage_dict_empty() -> None:
    result = _render_storage_dict({})
    assert result == ""


# ── _software_summary ────────────────────────────────────────────────────────


def test_software_summary_all_empty() -> None:
    node = _make_node()
    assert _software_summary(node) == "-"


def test_software_summary_with_counts() -> None:
    node = _make_node(
        software_apt_manual=["htop", "vim"],
        software_snaps=["core"],
        software_other=["docker"],
    )
    result = _software_summary(node)
    assert "apt:2" in result
    assert "snap:1" in result
    assert "other:1" in result
