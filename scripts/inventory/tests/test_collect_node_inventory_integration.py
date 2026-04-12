from __future__ import annotations

import ipaddress
import json
import sys
from pathlib import Path

import scripts.inventory.collect_node_inventory as collect_mod
import scripts.inventory.ssh_runner as ssh_runner
from scripts.inventory.generate_nodes_report_jsonc import strip_jsonc_comments


def test_collector_writes_nodes_yml_and_report_without_real_ssh(tmp_path: Path, monkeypatch) -> None:
    nodes_yml = tmp_path / "nodes.yml"
    report_jsonc = tmp_path / "nodes.report.jsonc"
    nodes_md = tmp_path / "nodes.md"

    remote_probe_json = json.dumps(
        {
            "hostname": "node-a",
            "platform": "Ubuntu 24.04",
            "kernel_release": "6.8.0-99-generic",
            "network_interfaces": [
                {
                    "name": "eth0",
                    "addresses": [f"{ipaddress.IPv4Address(0xC000020A)}/24"],
                }
            ],
            "cpu_model": "Test CPU",
            "cpu_cores": 4,
            "cpu_threads": 8,
            "memory_gb": 16,
            "gpus": ["00:02.0 VGA compatible controller: Intel UHD"],
            "storage": ["nvme0n1 1T TestDisk"],
            "apt_manual": ["htop"],
            "snaps": ["core"],
            "other": ["Docker version 27.0.0"],
        },
        ensure_ascii=False,
    )

    def fake_run_remote(
        *,
        host: str,
        user: str,
        port: int | None,
        identity_file: Path | None,
        remote_cmd: str,
        stdin_text: str | None = None,
    ) -> str:
        del host, user, port, identity_file
        if remote_cmd in {"python3 -", "sudo -n python3 -"}:
            assert stdin_text is not None
            assert "json.dumps" in stdin_text
            return remote_probe_json

        return ""

    monkeypatch.setattr(ssh_runner, "run_remote", fake_run_remote)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "collect_node_inventory",
            "--host",
            "dummy-host",
            "--user",
            "root",
            "--nodes-yml",
            str(nodes_yml),
            "--report-jsonc",
            str(report_jsonc),
            "--nodes-md",
            str(nodes_md),
        ],
    )

    collect_mod.main()

    assert nodes_yml.exists()
    assert report_jsonc.exists()
    assert nodes_md.exists()

    parsed = json.loads(strip_jsonc_comments(report_jsonc.read_text(encoding="utf-8")))
    assert "node-a" in parsed["nodes"]
    assert parsed["nodes"]["node-a"]["hardware"]["cpu"]["model"] == "Test CPU"
