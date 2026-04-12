from __future__ import annotations

import ipaddress
import json
from pathlib import Path

from scripts.inventory.generate_nodes_report_jsonc import (
    strip_jsonc_comments,
    write_nodes_report_jsonc,
)

_FIXTURES = Path(__file__).parent / "fixtures"


def test_generates_default_layout_when_nodes_yml_missing(tmp_path: Path) -> None:
    nodes_yml = tmp_path / "missing.yml"
    report = tmp_path / "report.jsonc"

    rendered = write_nodes_report_jsonc(nodes_yml, report)

    assert '"schema_version"' in rendered
    assert '"defaults"' in rendered
    assert '"nodes"' in rendered

    parsed = json.loads(strip_jsonc_comments(rendered))
    assert parsed["schema_version"] == 2
    assert parsed["nodes"] == {}


def test_maps_hostname_to_hardware_sections(tmp_path: Path) -> None:
    cidr = f"{ipaddress.IPv4Address(0xC000020A)}/24"

    nodes_yml = tmp_path / "nodes.yml"
    nodes_yml.write_text(
        (_FIXTURES / "nodes-with-hardware.yml").read_text(encoding="utf-8").replace("__CIDR__", cidr),
        encoding="utf-8",
    )

    report = tmp_path / "nodes.report.jsonc"
    rendered = write_nodes_report_jsonc(nodes_yml, report)

    parsed = json.loads(strip_jsonc_comments(rendered))
    node = parsed["nodes"]["prd-srv-control-01"]

    assert node["meta"]["roles"] == ["control"]
    assert node["hardware"]["cpu"]["model"] == "Intel(R) Xeon"
    assert node["meta"]["kernel"] == "6.8.0-99-generic"
    assert node["network"]["interfaces"] == [{"name": "eth0", "addresses": [cidr]}]
    assert node["hardware"]["cpu"]["cores"] == 4
    assert node["hardware"]["cpu"]["threads"] == 8
    assert node["hardware"]["memory_gb"] == 32
    assert node["hardware"]["gpus"] == ["Intel UHD"]
    assert node["hardware"]["storage"] == ["nvme0n1 1T"]
    assert node["software"]["apt_manual"] == ["htop"]
    assert node["software"]["other"] == ["docker version 27.0.0"]


def test_regeneration_removes_deprecated_sections(tmp_path: Path) -> None:
    nodes_yml = tmp_path / "nodes.yml"
    nodes_yml.write_text(
        (_FIXTURES / "nodes-minimal.yml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    report = tmp_path / "nodes.report.jsonc"
    report.write_text(
        (_FIXTURES / "deprecated-report.jsonc").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    rendered = write_nodes_report_jsonc(nodes_yml, report)

    # Deprecated/unknown keys should not survive regeneration
    assert '"deprecated"' not in rendered
    assert "old_section" not in rendered

    parsed = json.loads(strip_jsonc_comments(report.read_text(encoding="utf-8")))
    assert "deprecated" not in parsed
    assert "old_section" not in json.dumps(parsed)
