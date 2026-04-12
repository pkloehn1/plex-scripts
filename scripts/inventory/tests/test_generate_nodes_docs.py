from __future__ import annotations

import ipaddress
from pathlib import Path

from scripts.inventory.generate_nodes_docs import (
    NodeRecord,
    render_nodes_markdown,
    write_nodes_markdown,
)


def test_render_nodes_markdown_is_deterministic() -> None:
    addr = ipaddress.IPv4Address(0xC000020A)
    cidr = f"{addr}/24"

    records = [
        NodeRecord(
            hostname="node-b",
            roles=["compute"],
            platform="baremetal",
            kernel_release="6.8.0-99-generic",
            network_interfaces=[f"eth0: {cidr}"],
            cpu_model="Intel i5",
            cpu_cores=6,
            cpu_threads=12,
            memory_gb=32,
            gpus=["iGPU"],
            storage=["nvme 500GB"],
            software_apt_manual=["htop"],
            software_snaps=[],
            software_other=["docker version 27.0.0"],
            status="active",
            notes=None,
        ),
        NodeRecord(
            hostname="node-a",
            roles=[],
            platform=None,
            kernel_release=None,
            network_interfaces=[],
            cpu_model=None,
            cpu_cores=None,
            cpu_threads=None,
            memory_gb=None,
            gpus=[],
            storage=[],
            software_apt_manual=[],
            software_snaps=[],
            software_other=[],
            status=None,
            notes="",
        ),
    ]

    md1 = render_nodes_markdown(sorted(records, key=lambda rec: rec.hostname))
    md2 = render_nodes_markdown(sorted(records, key=lambda rec: rec.hostname))
    assert md1 == md2
    assert "| Group | Field | Value |" in md1
    assert "## Table of Contents" in md1
    assert "- [node-a](#node-a)" in md1
    assert "- [node-b](#node-b)" in md1
    assert "## node-a" in md1
    assert "## node-b" in md1
    assert "| Meta | Kernel | 6.8.0-99-generic |" in md1
    assert f"| Network | Interfaces | eth0: {cidr} |" in md1
    assert "| Hardware | CPU model | Intel i5 |" in md1
    assert "| Hardware | CPU cores | 6 |" in md1
    assert "| Hardware | CPU threads | 12 |" in md1


def test_write_nodes_markdown_from_yaml(tmp_path: Path) -> None:
    addr = ipaddress.IPv4Address(0xC000020A)
    cidr = f"{addr}/24"

    yml = tmp_path / "nodes.yml"
    md_out = tmp_path / "nodes.md"

    yml.write_text(
        "\n".join(
            [
                "---",
                "version: 1",
                "nodes:",
                "  - hostname: node-a",
                "    roles: [control]",
                "    platform: baremetal",
                "    kernel: 6.8.0-99-generic",
                "    network:",
                "      interfaces:",
                "        - name: eth0",
                f'          addresses: ["{cidr}"]',
                "    cpu:",
                "      model: Intel i5",
                "      cores: 6",
                "      threads: 12",
                "    memory_gb: 32",
                "    gpus: []",
                "    storage:",
                "      - type: nvme",
                "        size_gb: 512",
                "        notes: OS",
                "    status: active",
                "    notes: null",
                "",
            ]
        ),
        encoding="utf-8",
    )

    write_nodes_markdown(yml_path=yml, md_path=md_out)

    content = md_out.read_text(encoding="utf-8")
    assert "# Node Capabilities (Generated)" in content
    assert "## Table of Contents" in content
    assert "- [node-a](#node-a)" in content
    assert "## node-a" in content
    assert "| Meta | Kernel | 6.8.0-99-generic |" in content
    assert f"| Network | Interfaces | eth0: {cidr} |" in content
    assert "| Hardware | CPU model | Intel i5 |" in content
    assert "| Hardware | CPU cores | 6 |" in content
    assert "| Hardware | CPU threads | 12 |" in content
    assert "nvme 512GB OS" in content
