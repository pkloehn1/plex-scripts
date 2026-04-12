from __future__ import annotations

import ipaddress
import json
import re
import sys
from pathlib import Path

import scripts.inventory.collect_node_inventory as collect_mod
import scripts.inventory.ssh_runner as ssh_runner
from scripts.inventory.generate_nodes_report_jsonc import strip_jsonc_comments

_FIXTURES = Path(__file__).parent / "fixtures"


def _doc_ipv4(address_hex: int) -> str:
    """Return a TEST-NET IPv4 address without using dotted-quad literals."""
    return str(ipaddress.IPv4Address(address_hex))


def test_collector_all_collects_every_node_in_nodes_yml(tmp_path: Path, monkeypatch, capsys) -> None:
    nodes_yml = tmp_path / "nodes.yml"
    report_jsonc = tmp_path / "nodes.report.jsonc"
    nodes_md = tmp_path / "nodes.md"

    nodes_yml.write_text(
        (_FIXTURES / "nodes-two-hosts.yml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    probe_by_host: dict[str, str] = {
        "node-a": json.dumps(
            {
                "hostname": "node-a",
                "platform": "Ubuntu 24.04",
                "kernel_release": "6.8.0-99-generic",
                "network_interfaces": [
                    {
                        "name": "eth0",
                        "addresses": [f"{_doc_ipv4(0xC000020A)}/24"],
                    }
                ],
                "cpu_model": "CPU A",
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
        ),
        "node-b": json.dumps(
            {
                "hostname": "node-b",
                "platform": "Ubuntu 24.04",
                "kernel_release": "6.8.0-99-generic",
                "network_interfaces": [
                    {
                        "name": "eth0",
                        "addresses": [f"{_doc_ipv4(0xC000020B)}/24"],
                    }
                ],
                "cpu_model": "CPU B",
                "cpu_cores": 8,
                "cpu_threads": 16,
                "memory_gb": 32,
                "gpus": [],
                "storage": [],
                "apt_manual": [],
                "snaps": [],
                "other": [],
            },
            ensure_ascii=False,
        ),
    }

    def fake_run_remote(
        *,
        host: str,
        user: str,
        port: int | None,
        identity_file: Path | None,
        remote_cmd: str,
        stdin_text: str | None = None,
    ) -> str:
        del user, port, identity_file
        if remote_cmd == "true":
            return ""
        if remote_cmd == "python3 -":
            assert stdin_text is not None
            return probe_by_host[host]
        return ""

    monkeypatch.setattr(ssh_runner, "run_remote", fake_run_remote)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "collect_node_inventory",
            "--all",
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

    output = capsys.readouterr().out
    assert "Overall status report" in output
    assert re.search(r"^Hostname\s+Responded\s+Done\s+Error\s*$", output, re.M) is not None
    assert re.search(r"^node-a\s+yes\s+yes\b", output, re.M) is not None
    assert re.search(r"^node-b\s+yes\s+yes\b", output, re.M) is not None

    assert report_jsonc.exists()
    assert nodes_md.exists()

    parsed = json.loads(strip_jsonc_comments(report_jsonc.read_text(encoding="utf-8")))
    assert "node-a" in parsed["nodes"]
    assert "node-b" in parsed["nodes"]
    assert parsed["nodes"]["node-a"]["hardware"]["cpu"]["model"] == "CPU A"
    assert parsed["nodes"]["node-b"]["hardware"]["cpu"]["model"] == "CPU B"


def test_collector_all_prints_error_lookup_when_any_host_fails(tmp_path: Path, monkeypatch, capsys) -> None:
    nodes_yml = tmp_path / "nodes.yml"
    report_jsonc = tmp_path / "nodes.report.jsonc"
    nodes_md = tmp_path / "nodes.md"

    nodes_yml.write_text(
        (_FIXTURES / "nodes-two-hosts.yml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    probe_json = json.dumps(
        {
            "hostname": "node-a",
            "platform": "Ubuntu 24.04",
            "kernel_release": "6.8.0-99-generic",
            "network_interfaces": [
                {
                    "name": "eth0",
                    "addresses": [f"{_doc_ipv4(0xC000020A)}/24"],
                }
            ],
            "cpu_model": "CPU A",
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
        del user, port, identity_file
        if host == "node-b" and remote_cmd == "true":
            raise RuntimeError("Command failed (255): ssh ...")
        if remote_cmd == "true":
            return ""
        if remote_cmd == "python3 -":
            assert stdin_text is not None
            return probe_json
        return ""

    monkeypatch.setattr(ssh_runner, "run_remote", fake_run_remote)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "collect_node_inventory",
            "--all",
            "--continue-on-error",
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

    output = capsys.readouterr().out
    assert "Error lookup: docs/inventory/collector-error-codes.md" in output
    assert "INV-SSH-ALIVE-FAILED" in output
