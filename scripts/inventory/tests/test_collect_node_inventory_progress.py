from __future__ import annotations

import ipaddress
import json
import sys
from pathlib import Path

import scripts.inventory.collect_node_inventory as collect_mod
import scripts.inventory.ssh_runner as ssh_runner


def test_collector_emits_one_line_per_step_when_progress_enabled(tmp_path: Path, monkeypatch, capsys) -> None:
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
            "gpus": [],
            "storage": [],
            "apt_manual": [],
            "snaps": [],
            "other": [],
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
        if remote_cmd == "true":
            return ""
        if remote_cmd == "python3 -":
            assert stdin_text is not None
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

    captured = capsys.readouterr().out
    assert "[1/5] alive test" in captured
    assert "[2/5] remote python probe" in captured
    assert "[3/5] update nodes.yml" in captured
    assert "[4/5] generate report" in captured
    assert "[5/5] generate nodes.md" in captured
