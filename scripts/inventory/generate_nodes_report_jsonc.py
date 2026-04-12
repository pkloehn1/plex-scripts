from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

from ._nodes_yml_parsing import ParsedNodeBase
from ._nodes_yml_parsing import normalize_newlines as _normalize_newlines
from ._nodes_yml_parsing import parse_node_base_fields as _parse_node_base_fields
from ._nodes_yml_parsing import parse_str_list as _parse_str_list
from ._nodes_yml_parsing import read_text_if_exists as _read_text_if_exists

_REPO_ROOT = Path(__file__).resolve().parents[2]
_NODES_YML = _REPO_ROOT / "docs" / "inventory" / "nodes.yml"
_REPORT_JSONC = _REPO_ROOT / "docs" / "inventory" / "nodes.report.jsonc"

_SCHEMA_VERSION = 2


@dataclass(frozen=True, slots=True)
class ReportWriteResult:
    rendered: str
    changed: bool
    created: bool


@dataclass(frozen=True, slots=True)
class ReportNode(ParsedNodeBase):
    network_interfaces: list[dict[str, object]]
    storage: list[str]


def _consume_string(text: str, start: int) -> tuple[str, int]:
    pos = start
    out: list[str] = []
    escape = False

    while pos < len(text):
        char = text[pos]
        out.append(char)

        if escape:
            escape = False
        elif char == "\\":
            escape = True
        elif char == '"' and pos != start:
            return "".join(out), pos + 1

        pos += 1

    return "".join(out), pos


def _consume_line_comment(text: str, start: int) -> int:
    pos = start
    while pos < len(text) and text[pos] not in "\r\n":
        pos += 1
    return pos


def _consume_block_comment(text: str, start: int) -> int:
    pos = start + 2
    while pos < len(text) - 1:
        if text[pos] == "*" and text[pos + 1] == "/":
            return pos + 2
        pos += 1
    return len(text)


def strip_jsonc_comments(text: str) -> str:
    """Remove // and /* */ comments from JSONC.

    Used only for tests/debugging. Output is intended to be valid JSON.
    """
    out: list[str] = []
    pos = 0
    while pos < len(text):
        if text[pos] == '"':
            segment, pos = _consume_string(text, pos)
            out.append(segment)
            continue

        if text.startswith("//", pos):
            pos = _consume_line_comment(text, pos)
            continue

        if text.startswith("/*", pos):
            pos = _consume_block_comment(text, pos)
            continue

        out.append(text[pos])
        pos += 1

    return "".join(out)


def _load_nodes_records(nodes_yml: Path) -> list[ReportNode]:
    if not nodes_yml.exists():
        return []

    raw = yaml.safe_load(nodes_yml.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("nodes.yml must be a mapping")

    nodes = raw.get("nodes")
    if not isinstance(nodes, list):
        raise ValueError("nodes.yml must define a 'nodes' list")

    records: list[ReportNode] = []
    for node in nodes:
        base, interfaces = _parse_node_base_fields(node)
        storage = _parse_str_list(node, base.hostname, "storage") if isinstance(node, dict) else []
        network_dicts: list[dict[str, object]] = [
            {"name": iface.name, "addresses": iface.addresses} for iface in interfaces
        ]
        records.append(
            ReportNode(
                **asdict(base),
                network_interfaces=network_dicts,
                storage=storage,
            )
        )

    return sorted(records, key=lambda record: record.hostname)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_nodes_report_jsonc(records: list[ReportNode], *, generated_at: str) -> str:
    """Render a JSONC report mapping hostnames to hardware/software sections.

    Deprecated/unknown structures are removed by regeneration (SSOT-driven).
    """
    lines: list[str] = []
    lines.append("{")
    lines.append("  // Node inventory report (generated)")
    lines.append("  //")
    lines.append("  // Source of truth: docs/inventory/nodes.yml")
    lines.append("  // Generator: scripts/inventory/generate_nodes_report_jsonc.py")
    lines.append("  //")
    lines.append("  // This file is JSONC: JSON + comments. If you need strict JSON,")
    lines.append("  // strip comments first.")
    lines.append(f'  "schema_version": {_SCHEMA_VERSION},')
    lines.append("  // ISO-8601 UTC timestamp")
    lines.append(f'  "generated_at": {_json(generated_at)},')
    lines.append("  // Default layout for each node entry")
    lines.append('  "defaults": {')
    lines.append('    "meta": {')
    lines.append("      // Inventory roles (used for placement planning/grouping)")
    lines.append('      "roles": [],')
    lines.append("      // OS/platform string (e.g., PRETTY_NAME from /etc/os-release)")
    lines.append('      "platform": null,')
    lines.append("      // uname -r")
    lines.append('      "kernel": null,')
    lines.append('      "status": null,')
    lines.append('      "notes": null')
    lines.append("    },")
    lines.append('    "hardware": {')
    lines.append('      "cpu": {"model": null, "cores": null, "threads": null},')
    lines.append('      "memory_gb": null,')
    lines.append('      "gpus": [],')
    lines.append('      "storage": []')
    lines.append("    },")
    lines.append('    "software": {')
    lines.append("      // apt-mark showmanual")
    lines.append('      "apt_manual": [],')
    lines.append("      // snap list (names only)")
    lines.append('      "snaps": [],')
    lines.append("      // Tool/version probes (docker, compose, containerd, etc.)")
    lines.append('      "other": []')
    lines.append("    }")
    lines.append("    ,")
    lines.append('    "network": {')
    lines.append("      // Interface/IP inventory")
    lines.append('      "interfaces": []')
    lines.append("    }")
    lines.append("  },")
    lines.append("  // Nodes keyed by hostname")
    lines.append('  "nodes": {')

    for idx, node in enumerate(records):
        is_last = idx == len(records) - 1
        lines.append(f"    // {node.hostname}")
        lines.append(f"    {_json(node.hostname)}: {{")
        lines.append('      "meta": {')
        lines.append(f'        "roles": {_json(node.roles)},')
        lines.append(f'        "platform": {_json(node.platform)},')
        lines.append(f'        "kernel": {_json(node.kernel_release)},')
        lines.append(f'        "status": {_json(node.status)},')
        lines.append(f'        "notes": {_json(node.notes)}')
        lines.append("      },")
        lines.append('      "hardware": {')
        lines.append('        "cpu": {')
        lines.append(f'          "model": {_json(node.cpu_model)},')
        lines.append(f'          "cores": {_json(node.cpu_cores)},')
        lines.append(f'          "threads": {_json(node.cpu_threads)}')
        lines.append("        },")
        lines.append(f'        "memory_gb": {_json(node.memory_gb)},')
        lines.append(f'        "gpus": {_json(node.gpus)},')
        lines.append(f'        "storage": {_json(node.storage)}')
        lines.append("      },")
        lines.append('      "software": {')
        lines.append(f'        "apt_manual": {_json(node.software_apt_manual)},')
        lines.append(f'        "snaps": {_json(node.software_snaps)},')
        lines.append(f'        "other": {_json(node.software_other)}')
        lines.append("      }")
        lines.append("      ,")
        lines.append('      "network": {')
        lines.append(f'        "interfaces": {_json(node.network_interfaces)}')
        lines.append("      }")
        lines.append(f"    }}{'' if is_last else ','}")

    lines.append("  }")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _generated_at_from_nodes_yml(nodes_yml: Path) -> str:
    if nodes_yml.exists():
        timestamp = nodes_yml.stat().st_mtime
        return datetime.fromtimestamp(timestamp, tz=UTC).replace(microsecond=0).isoformat()
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def write_nodes_report_jsonc_result(nodes_yml: Path, report_path: Path) -> ReportWriteResult:
    existing_text = _read_text_if_exists(report_path)
    created = existing_text is None

    records = _load_nodes_records(nodes_yml)
    generated_at = _generated_at_from_nodes_yml(nodes_yml)
    rendered = render_nodes_report_jsonc(records, generated_at=generated_at)

    rendered_normalized = _normalize_newlines(rendered)
    existing_normalized = _normalize_newlines(existing_text) if existing_text is not None else None
    changed = created or existing_normalized != rendered_normalized

    if changed:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered, encoding="utf-8")

    return ReportWriteResult(rendered=rendered, changed=changed, created=created)


def write_nodes_report_jsonc(nodes_yml: Path, report_path: Path) -> str:
    return write_nodes_report_jsonc_result(nodes_yml, report_path).rendered


def _parse_args() -> argparse.Namespace:  # pragma: no cover
    parser = argparse.ArgumentParser(description="Generate JSONC node inventory report from docs/inventory/nodes.yml")
    parser.add_argument(
        "--nodes-yml",
        type=Path,
        default=_NODES_YML,
        help="Path to nodes.yml SSOT",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_REPORT_JSONC,
        help="Output path for the JSONC report",
    )
    return parser.parse_args()


def main() -> None:  # pragma: no cover
    args = _parse_args()
    write_nodes_report_jsonc(args.nodes_yml, args.out)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
