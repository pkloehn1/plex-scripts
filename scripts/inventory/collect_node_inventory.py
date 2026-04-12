from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import scripts.inventory.ssh_runner as ssh_runner
from scripts.common.paths import repo_root
from scripts.inventory.inventory_types import (
    CollectedInventory,
    HostRunStatus,
    HostTarget,
    NetworkInterface,
    UpdateResult,
)
from scripts.inventory.nodes_yml import (
    host_targets_from_nodes_yml,
    update_nodes_yml,
)
from scripts.inventory.reporting import (
    Progress,
    print_all_hosts_status_report,
)

_REPO_ROOT = repo_root()
_NODES_YML = _REPO_ROOT / "docs" / "inventory" / "nodes.yml"
_REPORT_JSONC = _REPO_ROOT / "docs" / "inventory" / "nodes.report.jsonc"
_NODES_MD = _REPO_ROOT / "docs" / "inventory" / "nodes.md"


def _parse_first_match(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, flags=re.MULTILINE)
    if not match:
        return None
    value = match.group(1).strip()
    return value or None


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_first_int(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.search(r"(\d+)", value)
    if not match:
        return None
    return _parse_int(match.group(1))


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


_REMOTE_PYTHON_COLLECTOR = (Path(__file__).parent / "remote_probe.py").read_text()


def _parse_remote_python_json(raw: str) -> dict[str, object]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Remote python did not return JSON: {raw[:200]}") from exc

    if not isinstance(parsed, dict):
        raise RuntimeError("Remote python returned non-object JSON")
    return parsed


def _json_opt_str(obj: dict[str, object], key: str) -> str | None:
    val = obj.get(key)
    if not isinstance(val, str):
        return None
    val = val.strip()
    return val or None


def _json_opt_int(obj: dict[str, object], key: str) -> int | None:
    val = obj.get(key)
    if isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val
    return None


def _json_str_list(obj: dict[str, object], key: str) -> list[str]:
    val = obj.get(key)
    if val is None:
        return []
    if not isinstance(val, list) or not all(isinstance(item, str) for item in val):
        return []
    return [item.strip() for item in val if item.strip()]


def _json_network_interfaces(obj: dict[str, object]) -> list[NetworkInterface]:
    raw = obj.get("network_interfaces")
    if raw is None:
        return []
    if not isinstance(raw, list):
        return []

    parsed: list[NetworkInterface] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        addresses = item.get("addresses")
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(addresses, list) or not all(isinstance(addr, str) for addr in addresses):
            continue

        cleaned = [addr.strip() for addr in addresses if addr.strip()]
        cleaned = sorted(_dedupe_preserve_order(cleaned))
        if not cleaned:
            continue

        parsed.append(NetworkInterface(name=name.strip(), addresses=cleaned))

    parsed.sort(key=lambda iface: iface.name)
    return parsed


def _json_required_hostname(obj: dict[str, object]) -> str:
    hostname = obj.get("hostname")
    if not isinstance(hostname, str) or not hostname.strip():
        raise RuntimeError("Remote python did not return a hostname")
    return hostname.strip()


def _collect_inventory_remote_python(runner: ssh_runner.Runner, *, sudo: bool) -> CollectedInventory:
    raw = runner.run_remote_python(_REMOTE_PYTHON_COLLECTOR, sudo=sudo).strip()
    parsed = _parse_remote_python_json(raw)
    hostname = _json_required_hostname(parsed)

    return CollectedInventory(
        hostname=hostname,
        platform=_json_opt_str(parsed, "platform"),
        kernel_release=_json_opt_str(parsed, "kernel_release"),
        network_interfaces=_json_network_interfaces(parsed),
        cpu_model=_json_opt_str(parsed, "cpu_model"),
        cpu_cores=_json_opt_int(parsed, "cpu_cores"),
        cpu_threads=_json_opt_int(parsed, "cpu_threads"),
        memory_gb=_json_opt_int(parsed, "memory_gb"),
        gpus=_dedupe_preserve_order(_json_str_list(parsed, "gpus")),
        storage=_dedupe_preserve_order(_json_str_list(parsed, "storage")),
        apt_manual=_dedupe_preserve_order(_json_str_list(parsed, "apt_manual")),
        snaps=_dedupe_preserve_order(_json_str_list(parsed, "snaps")),
        other=_dedupe_preserve_order(_json_str_list(parsed, "other")),
    )


_STEP_UPDATE_NODES_YML = "update nodes.yml"
_STEP_ALIVE_TEST = "alive test"
_STEP_REMOTE_PYTHON_PROBE = "remote python probe"
_STEP_GENERATE_REPORT = "generate report"
_STEP_GENERATE_DOCS = "generate nodes.md"


def _collect_platform(runner: ssh_runner.Runner) -> str | None:
    os_release = runner.run("cat /etc/os-release 2>/dev/null || true")
    return _parse_first_match(os_release, r"^PRETTY_NAME=(?:\"|')?(.*?)(?:\"|')?$")


def _collect_kernel_release(runner: ssh_runner.Runner) -> str | None:
    return runner.run("uname -r").strip() or None


_EXCLUDED_NETWORK_IFACE_PREFIX = re.compile(r"^(veth|br-|docker|virbr|cni|flannel|calico|podman)")


def _include_network_interface(name: str) -> bool:
    if name == "lo":
        return False
    return _EXCLUDED_NETWORK_IFACE_PREFIX.match(name) is None


def _extract_ip_addresses(addr_info: object) -> list[str]:
    if not isinstance(addr_info, list):
        return []

    addresses: list[str] = []
    for addr in addr_info:
        if not isinstance(addr, dict):
            continue
        family = addr.get("family")
        if family not in ("inet", "inet6"):
            continue
        local = addr.get("local")
        if not isinstance(local, str) or not local.strip():
            continue
        scope = addr.get("scope")
        if scope == "link":
            continue
        prefixlen = addr.get("prefixlen")
        if not isinstance(prefixlen, int):
            continue
        addresses.append(f"{local.strip()}/{prefixlen}")

    return sorted(_dedupe_preserve_order(addresses))


def _collect_network_interfaces_shell(
    runner: ssh_runner.Runner,
) -> list[NetworkInterface]:
    raw = runner.run("(command -v ip >/dev/null 2>&1 && ip -j address show) || true")
    raw = raw.strip()
    if not raw:
        return []

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []

    interfaces: list[NetworkInterface] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        name = item.get("ifname")
        if not isinstance(name, str) or not name.strip():
            continue
        name = name.strip()
        if not _include_network_interface(name):
            continue

        addresses = _extract_ip_addresses(item.get("addr_info"))
        if addresses:
            interfaces.append(NetworkInterface(name=name, addresses=addresses))

    interfaces.sort(key=lambda iface: iface.name)
    return interfaces


def _parse_lscpu_json(raw: str) -> dict[str, str]:
    raw = raw.strip()
    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}

    if not isinstance(parsed, dict):
        return {}

    rows = parsed.get("lscpu")
    if not isinstance(rows, list):
        return {}

    fields: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        field = row.get("field")
        data = row.get("data")
        if not isinstance(field, str) or not isinstance(data, str):
            continue
        key = field.strip().rstrip(":").strip()
        value = data.strip()
        if key and value:
            fields[key] = value
    return fields


def _collect_cpu(
    runner: ssh_runner.Runner,
) -> tuple[str | None, int | None, int | None]:
    lscpu_raw = runner.run("(command -v lscpu >/dev/null 2>&1 && lscpu -J) || true")
    fields = _parse_lscpu_json(lscpu_raw)

    cpu_model = fields.get("Model name")

    threads = _parse_first_int(fields.get("CPU(s)"))

    cpu_cores: int | None = None
    cores_total = _parse_first_int(fields.get("Core(s)"))
    if cores_total is not None:
        cpu_cores = cores_total
    else:
        cores_per_socket = _parse_first_int(fields.get("Core(s) per socket"))
        sockets = _parse_first_int(fields.get("Socket(s)"))
        if cores_per_socket is not None and sockets is not None:
            cpu_cores = cores_per_socket * sockets

    return cpu_model, cpu_cores, threads


def _collect_memory_gb(runner: ssh_runner.Runner) -> int | None:
    meminfo = runner.run("cat /proc/meminfo 2>/dev/null || true")
    mem_kb = _parse_int(_parse_first_match(meminfo, r"^MemTotal:\s+(\d+)\s+kB"))
    if mem_kb is None:
        return None
    return round((mem_kb * 1024) / (1024**3))


_GPU_DEVICE_RE = re.compile(r"VGA compatible controller|3D controller|Display controller")


def _collect_gpus(runner: ssh_runner.Runner) -> list[str]:
    lspci_out = runner.run("(command -v lspci >/dev/null 2>&1 && lspci) || true")
    return [line.strip() for line in lspci_out.splitlines() if line.strip() and _GPU_DEVICE_RE.search(line)]


def _parse_lsblk_disk_line(line: str) -> str | None:
    """Parse a single lsblk output line, returning 'name size model' for disk devices."""
    stripped = line.strip()
    if not stripped or stripped.startswith("NAME"):
        return None
    parts = stripped.split()
    if len(parts) < 4 or parts[-1] != "disk":
        return None
    name, size = parts[0], parts[1]
    model = " ".join(parts[2:-1]).strip() or "unknown"
    return f"{name} {size} {model}"


def _collect_storage(runner: ssh_runner.Runner) -> list[str]:
    lsblk = runner.run("(command -v lsblk >/dev/null 2>&1 && lsblk -d -o NAME,SIZE,MODEL,TYPE) || true")
    return [entry for line in lsblk.splitlines() if (entry := _parse_lsblk_disk_line(line))]


def _parse_snap_name(line: str) -> str | None:
    """Extract the snap package name from a snap-list output line."""
    if line.strip().startswith("Name"):
        return None
    cols = line.split()
    return cols[0] if cols else None


_SOFTWARE_VERSION_CMDS = (
    "docker --version",
    "docker compose version",
    "containerd --version",
    "podman --version",
)


def _collect_software(
    runner: ssh_runner.Runner,
) -> tuple[list[str], list[str], list[str]]:
    apt_manual_raw = runner.run("(command -v apt-mark >/dev/null 2>&1 && apt-mark showmanual) || true")
    apt_manual = [line.strip() for line in apt_manual_raw.splitlines() if line.strip()]

    snaps_raw = runner.run("(command -v snap >/dev/null 2>&1 && snap list) || true")
    snaps = [name for line in snaps_raw.splitlines() if (name := _parse_snap_name(line))]

    other = [out for cmd in _SOFTWARE_VERSION_CMDS if (out := runner.run(f"({cmd}) 2>/dev/null || true").strip())]

    return apt_manual, snaps, other


def collect_inventory(runner: ssh_runner.Runner, progress: Progress | None = None) -> CollectedInventory:
    hostname = runner.run("hostname").strip()
    if progress is not None:
        progress.advance("hostname")

    platform = _collect_platform(runner)
    if progress is not None:
        progress.advance("platform")

    kernel_release = _collect_kernel_release(runner)
    if progress is not None:
        progress.advance("kernel")

    network_interfaces = _collect_network_interfaces_shell(runner)
    if progress is not None:
        progress.advance("network")

    cpu_model, cpu_cores, cpu_threads = _collect_cpu(runner)
    if progress is not None:
        progress.advance("cpu")

    memory_gb = _collect_memory_gb(runner)
    if progress is not None:
        progress.advance("memory")

    gpus = _collect_gpus(runner)
    if progress is not None:
        progress.advance("gpu")

    storage = _collect_storage(runner)
    if progress is not None:
        progress.advance("storage")

    apt_manual, snaps, other = _collect_software(runner)
    if progress is not None:
        progress.advance("software")

    return CollectedInventory(
        hostname=hostname,
        platform=platform,
        kernel_release=kernel_release,
        network_interfaces=network_interfaces,
        cpu_model=cpu_model,
        cpu_cores=cpu_cores,
        cpu_threads=cpu_threads,
        memory_gb=memory_gb,
        gpus=_dedupe_preserve_order(gpus),
        storage=_dedupe_preserve_order(storage),
        apt_manual=_dedupe_preserve_order(apt_manual),
        snaps=_dedupe_preserve_order(snaps),
        other=_dedupe_preserve_order(other),
    )


def _parse_args() -> argparse.Namespace:  # pragma: no cover
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description=(
            "Collect node inventory facts (hardware + non-stock software) and update docs/inventory/nodes.yml"
        ),
    )

    host_group = parser.add_mutually_exclusive_group(required=False)
    host_group.add_argument(
        "--host",
        help="Remote hostname or IP to SSH into. If omitted, runs locally.",
        default=None,
    )
    host_group.add_argument(
        "--all",
        help="Collect inventory for all hostnames listed in nodes.yml.",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--user",
        help=(
            "SSH user (default). In --all mode, can be overridden per node via nodes.yml "
            "using either 'ssh_user' or 'ssh: { user: ... }'."
        ),
        default="alvis-andrews",
    )
    parser.add_argument("--port", help="SSH port", type=int, default=None)
    parser.add_argument(
        "--identity-file",
        help="SSH identity file",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--remote-mode",
        help="Remote collection mode when using --host",
        choices=["python", "shell"],
        default="python",
    )
    parser.add_argument(
        "--remote-python-sudo",
        help="Run remote python probe via sudo -n python3 - (requires passwordless sudo)",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--nodes-yml",
        help="Path to nodes.yml SSOT",
        type=Path,
        default=_NODES_YML,
    )
    parser.add_argument(
        "--report-jsonc",
        help="Path to generated JSONC report",
        type=Path,
        default=_REPORT_JSONC,
    )
    parser.add_argument(
        "--nodes-md",
        help="Path to generated Markdown doc",
        type=Path,
        default=_NODES_MD,
    )
    parser.add_argument(
        "--dry-run",
        help="Print resulting YAML but do not write it",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--continue-on-error",
        help="When using --all, continue collecting other hosts if one host fails",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--no-progress",
        help=argparse.SUPPRESS,
        action="store_true",
        default=False,
    )
    return parser.parse_args()


def _collect_one_and_update_nodes_yml(
    *,
    host: str | None,
    user: str,
    port: int | None,
    identity_file: Path | None,
    remote_mode: str,
    remote_python_sudo: bool,
    nodes_yml_path: Path,
    dry_run: bool,
    include_output_steps: bool,
) -> tuple[CollectedInventory, UpdateResult, Progress]:
    runner = ssh_runner.Runner(host, user, port, identity_file)
    use_remote_python = host is not None and remote_mode == "python"

    if host is not None:
        try:
            runner.check_alive()
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(f"alive test failed: {exc}") from exc

    steps_dry_run = dry_run or (not include_output_steps)
    steps = (
        _steps_for_remote_python(dry_run=steps_dry_run)
        if use_remote_python
        else _steps_for_shell(dry_run=steps_dry_run)
    )
    if host is not None:
        steps = [_STEP_ALIVE_TEST, *steps]
    progress = Progress(steps=steps, enabled=include_output_steps)
    progress.banner()

    if host is not None:
        progress.advance(_STEP_ALIVE_TEST)

    if use_remote_python:
        inv = _collect_inventory_remote_python(
            runner,
            sudo=remote_python_sudo,
        )
        progress.advance(_STEP_REMOTE_PYTHON_PROBE)
    else:
        inv = collect_inventory(runner, progress=progress)

    result = update_nodes_yml(nodes_yml_path, inv, dry_run=dry_run)
    progress.advance(_STEP_UPDATE_NODES_YML)
    return inv, result, progress


def _classify_host_error(error_text: str) -> tuple[bool, str, str]:
    text = error_text.strip()
    if text.startswith("alive test failed:"):
        detail = text.removeprefix("alive test failed:").strip()
        return False, "INV-SSH-ALIVE-FAILED", detail

    if "Host key verification failed." in text:
        return True, "INV-SSH-HOSTKEY", text

    if text.startswith("Command failed ("):
        return True, "INV-SSH-CMD-FAILED", text

    if "remote python" in text and "failed" in text:
        return True, "INV-REMOTE-PROBE-FAILED", text

    if "JSON" in text and ("decode" in text or "parse" in text):
        return True, "INV-REMOTE-PROBE-PARSE", text

    if "nodes.yml" in text and ("update" in text or "write" in text):
        return True, "INV-NODES-YML-UPDATE", text

    return True, "INV-UNKNOWN", text or "Unknown error"


def _collect_all_hosts(
    *,
    targets: list[HostTarget],
    port: int | None,
    identity_file: Path | None,
    remote_mode: str,
    remote_python_sudo: bool,
    nodes_yml_path: Path,
    continue_on_error: bool,
) -> tuple[list[HostRunStatus], bool]:
    any_changed = False
    statuses: list[HostRunStatus] = []

    for target in targets:
        hostname = target.hostname
        try:
            _status, result, _output = _collect_one_and_update_nodes_yml(
                host=hostname,
                user=target.user,
                port=port,
                identity_file=identity_file,
                remote_mode=remote_mode,
                remote_python_sudo=remote_python_sudo,
                nodes_yml_path=nodes_yml_path,
                dry_run=False,
                include_output_steps=False,
            )
            any_changed |= result.changed
            statuses.append(
                HostRunStatus(
                    hostname=hostname,
                    responded=True,
                    all_steps_completed=True,
                    error_code=None,
                    error_detail=None,
                )
            )
        except (RuntimeError, OSError, subprocess.SubprocessError, ValueError) as exc:
            if not continue_on_error:
                raise
            error_text = str(exc).strip() or exc.__class__.__name__
            responded, error_code, error_detail = _classify_host_error(error_text)
            statuses.append(
                HostRunStatus(
                    hostname=hostname,
                    responded=responded,
                    all_steps_completed=False,
                    error_code=error_code,
                    error_detail=error_detail,
                )
            )
    return statuses, any_changed


def _steps_for_remote_python(*, dry_run: bool) -> list[str]:
    steps = [_STEP_REMOTE_PYTHON_PROBE, _STEP_UPDATE_NODES_YML]
    if not dry_run:
        steps.append(_STEP_GENERATE_REPORT)
        steps.append(_STEP_GENERATE_DOCS)
    return steps


def _steps_for_shell(*, dry_run: bool) -> list[str]:
    steps = [
        "hostname",
        "platform",
        "kernel",
        "network",
        "cpu",
        "memory",
        "gpu",
        "storage",
        "software",
        _STEP_UPDATE_NODES_YML,
    ]
    if not dry_run:
        steps.append(_STEP_GENERATE_REPORT)
        steps.append(_STEP_GENERATE_DOCS)
    return steps


def _print_update_status(
    *,
    nodes_yml_path: Path,
    report_jsonc_path: Path,
    hostname: str,
    result: UpdateResult,
    report_result: Any,
) -> None:
    if result.created:
        print(f"Action: created nodes.yml + node entry for host {hostname}")
    elif result.node_created:
        print(f"Action: created node entry for host {hostname}")
    elif result.node_changed:
        print(f"Action: updated node entry for host {hostname}")
    elif result.changed:
        print(f"Action: updated {nodes_yml_path} (non-node change)")
    else:
        print(f"Action: no changes for {nodes_yml_path} (host {hostname})")

    if report_result.created:
        print(f"Created report {report_jsonc_path}")
    elif report_result.changed:
        print(f"Updated report {report_jsonc_path}")
    else:
        print(f"No changes for report {report_jsonc_path}")


def _write_report_and_advance(
    *,
    nodes_yml_path: Path,
    report_jsonc_path: Path,
    progress: Progress,
) -> Any:
    from scripts.inventory.generate_nodes_report_jsonc import (
        write_nodes_report_jsonc_result,
    )

    report_result = write_nodes_report_jsonc_result(nodes_yml_path, report_jsonc_path)
    progress.advance(_STEP_GENERATE_REPORT)
    return report_result


def _write_nodes_md_and_advance(
    *,
    nodes_yml_path: Path,
    nodes_md_path: Path,
    progress: Progress,
) -> None:
    from scripts.inventory.generate_nodes_docs import write_nodes_markdown

    write_nodes_markdown(yml_path=nodes_yml_path, md_path=nodes_md_path)
    progress.advance(_STEP_GENERATE_DOCS)


def main() -> None:  # pragma: no cover
    args = _parse_args()

    if args.all and args.dry_run:
        raise ValueError("--all cannot be used with --dry-run")

    if args.all:
        targets = host_targets_from_nodes_yml(args.nodes_yml, default_user=args.user)
        if not targets:
            raise RuntimeError(f"No hostnames found in {args.nodes_yml}")

        print(f"Collecting inventory for {len(targets)} hosts")

        statuses, any_changed = _collect_all_hosts(
            targets=targets,
            port=args.port,
            identity_file=args.identity_file,
            remote_mode=args.remote_mode,
            remote_python_sudo=args.remote_python_sudo,
            nodes_yml_path=args.nodes_yml,
            continue_on_error=args.continue_on_error,
        )

        progress = Progress(steps=[_STEP_GENERATE_REPORT, _STEP_GENERATE_DOCS])
        progress.banner()
        report_result = _write_report_and_advance(
            nodes_yml_path=args.nodes_yml,
            report_jsonc_path=args.report_jsonc,
            progress=progress,
        )
        _write_nodes_md_and_advance(
            nodes_yml_path=args.nodes_yml,
            nodes_md_path=args.nodes_md,
            progress=progress,
        )

        if report_result.created:
            print(f"Created report {args.report_jsonc}")
        elif report_result.changed or any_changed:
            print(f"Updated report {args.report_jsonc}")
        else:
            print(f"No changes for report {args.report_jsonc}")
        print(f"Wrote docs {args.nodes_md}")

        # End-of-run summary for fleet mode.
        print_all_hosts_status_report(
            statuses,
            report_completed=True,
            docs_completed=True,
        )
        return

    inv, result, progress = _collect_one_and_update_nodes_yml(
        host=args.host,
        user=args.user,
        port=args.port,
        identity_file=args.identity_file,
        remote_mode=args.remote_mode,
        remote_python_sudo=args.remote_python_sudo,
        nodes_yml_path=args.nodes_yml,
        dry_run=args.dry_run,
        include_output_steps=not args.dry_run,
    )
    if args.dry_run:
        print(result.rendered)
        return

    report_result = _write_report_and_advance(
        nodes_yml_path=args.nodes_yml,
        report_jsonc_path=args.report_jsonc,
        progress=progress,
    )
    _write_nodes_md_and_advance(
        nodes_yml_path=args.nodes_yml,
        nodes_md_path=args.nodes_md,
        progress=progress,
    )
    _print_update_status(
        nodes_yml_path=args.nodes_yml,
        report_jsonc_path=args.report_jsonc,
        hostname=inv.hostname,
        result=result,
        report_result=report_result,
    )


if __name__ == "__main__":
    main()
