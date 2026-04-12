from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import scripts.inventory.ssh_runner as ssh_runner_mod
from scripts.inventory.collect_node_inventory import (
    _classify_host_error,
    _collect_all_hosts,
    _collect_cpu,
    _collect_gpus,
    _collect_kernel_release,
    _collect_memory_gb,
    _collect_network_interfaces_shell,
    _collect_one_and_update_nodes_yml,
    _collect_platform,
    _collect_software,
    _collect_storage,
    _dedupe_preserve_order,
    _extract_ip_addresses,
    _include_network_interface,
    _json_network_interfaces,
    _json_opt_int,
    _json_opt_str,
    _json_required_hostname,
    _json_str_list,
    _parse_first_int,
    _parse_first_match,
    _parse_int,
    _parse_lsblk_disk_line,
    _parse_lscpu_json,
    _parse_remote_python_json,
    _parse_snap_name,
    _print_update_status,
    _steps_for_remote_python,
    _steps_for_shell,
    collect_inventory,
)
from scripts.inventory.inventory_types import HostTarget, UpdateResult

# ── _parse_first_match ────────────────────────────────────────────────────────


def test_parse_first_match_no_match_returns_none() -> None:
    assert _parse_first_match("hello world", r"^MISSING=(.*)$") is None


def test_parse_first_match_empty_group_returns_none() -> None:
    assert _parse_first_match("KEY=", r"^KEY=(.*)$") is None


def test_parse_first_match_returns_stripped_value() -> None:
    assert _parse_first_match("KEY=  hello  ", r"^KEY=(.*)$") == "hello"


# ── _parse_int ────────────────────────────────────────────────────────────────


def test_parse_int_none_returns_none() -> None:
    assert _parse_int(None) is None


def test_parse_int_valid() -> None:
    assert _parse_int("42") == 42


def test_parse_int_invalid_returns_none() -> None:
    assert _parse_int("abc") is None


# ── _parse_first_int ─────────────────────────────────────────────────────────


def test_parse_first_int_none_returns_none() -> None:
    assert _parse_first_int(None) is None


def test_parse_first_int_no_digits_returns_none() -> None:
    assert _parse_first_int("no digits here") is None


def test_parse_first_int_extracts_first_number() -> None:
    assert _parse_first_int("CPU(s): 8") == 8


# ── _dedupe_preserve_order ───────────────────────────────────────────────────


def test_dedupe_preserve_order_removes_duplicates() -> None:
    result = _dedupe_preserve_order(["b", "a", "b", "c", "a"])
    assert result == ["b", "a", "c"]


# ── _parse_remote_python_json ─────────────────────────────────────────────────


def test_parse_remote_python_json_invalid_json_raises() -> None:
    with pytest.raises(RuntimeError, match="Remote python did not return JSON"):
        _parse_remote_python_json("not json {")


def test_parse_remote_python_json_non_dict_raises() -> None:
    with pytest.raises(RuntimeError, match="non-object JSON"):
        _parse_remote_python_json("[1, 2, 3]")


def test_parse_remote_python_json_valid() -> None:
    result = _parse_remote_python_json('{"hostname": "myhost"}')
    assert result == {"hostname": "myhost"}


# ── _json_opt_str ─────────────────────────────────────────────────────────────


def test_json_opt_str_non_string_returns_none() -> None:
    assert _json_opt_str({"key": 42}, "key") is None


def test_json_opt_str_empty_string_returns_none() -> None:
    assert _json_opt_str({"key": "   "}, "key") is None


def test_json_opt_str_valid() -> None:
    assert _json_opt_str({"key": "value"}, "key") == "value"


# ── _json_opt_int ─────────────────────────────────────────────────────────────


def test_json_opt_int_bool_returns_none() -> None:
    assert _json_opt_int({"key": True}, "key") is None


def test_json_opt_int_int_returns_value() -> None:
    assert _json_opt_int({"key": 8}, "key") == 8


def test_json_opt_int_non_int_returns_none() -> None:
    assert _json_opt_int({"key": "8"}, "key") is None


# ── _json_str_list ────────────────────────────────────────────────────────────


def test_json_str_list_missing_key_returns_empty() -> None:
    assert _json_str_list({}, "key") == []


def test_json_str_list_non_list_returns_empty() -> None:
    assert _json_str_list({"key": "not-a-list"}, "key") == []


def test_json_str_list_non_string_items_returns_empty() -> None:
    assert _json_str_list({"key": [1, 2]}, "key") == []


def test_json_str_list_valid() -> None:
    assert _json_str_list({"key": [" a ", "b", "  "]}, "key") == ["a", "b"]


# ── _json_network_interfaces ──────────────────────────────────────────────────


def test_json_network_interfaces_missing_returns_empty() -> None:
    assert _json_network_interfaces({}) == []


def test_json_network_interfaces_non_list_returns_empty() -> None:
    assert _json_network_interfaces({"network_interfaces": "bad"}) == []


def test_json_network_interfaces_skips_non_dict_items() -> None:
    result = _json_network_interfaces({"network_interfaces": ["not-a-dict"]})
    assert result == []


def test_json_network_interfaces_skips_empty_name() -> None:
    result = _json_network_interfaces({"network_interfaces": [{"name": "", "addresses": ["1.2.3.4/24"]}]})
    assert result == []


def test_json_network_interfaces_skips_non_list_addresses() -> None:
    result = _json_network_interfaces({"network_interfaces": [{"name": "eth0", "addresses": "bad"}]})
    assert result == []


def test_json_network_interfaces_skips_empty_cleaned_addresses() -> None:
    result = _json_network_interfaces({"network_interfaces": [{"name": "eth0", "addresses": ["   "]}]})
    assert result == []


def test_json_network_interfaces_valid() -> None:
    result = _json_network_interfaces({"network_interfaces": [{"name": "eth0", "addresses": ["192.0.2.1/24"]}]})
    assert len(result) == 1
    assert result[0].name == "eth0"


# ── _json_required_hostname ───────────────────────────────────────────────────


def test_json_required_hostname_missing_raises() -> None:
    with pytest.raises(RuntimeError, match="did not return a hostname"):
        _json_required_hostname({})


def test_json_required_hostname_empty_raises() -> None:
    with pytest.raises(RuntimeError, match="did not return a hostname"):
        _json_required_hostname({"hostname": "  "})


# ── _include_network_interface ────────────────────────────────────────────────


def test_include_network_interface_excludes_lo() -> None:
    assert _include_network_interface("lo") is False


def test_include_network_interface_excludes_docker() -> None:
    assert _include_network_interface("docker0") is False


def test_include_network_interface_includes_eth0() -> None:
    assert _include_network_interface("eth0") is True


# ── _extract_ip_addresses ─────────────────────────────────────────────────────


def test_extract_ip_addresses_non_list_returns_empty() -> None:
    assert _extract_ip_addresses("bad") == []


def test_extract_ip_addresses_skips_non_dict() -> None:
    assert _extract_ip_addresses(["not-a-dict"]) == []


def test_extract_ip_addresses_skips_wrong_family() -> None:
    addr = {"family": "link", "local": "aa:bb:cc:dd:ee:ff", "prefixlen": 0}
    assert _extract_ip_addresses([addr]) == []


def test_extract_ip_addresses_skips_link_scope() -> None:
    addr = {"family": "inet6", "local": "fe80::1", "prefixlen": 64, "scope": "link"}
    assert _extract_ip_addresses([addr]) == []


def test_extract_ip_addresses_skips_non_int_prefixlen() -> None:
    addr = {"family": "inet", "local": "192.0.2.1", "prefixlen": "24", "scope": "global"}
    assert _extract_ip_addresses([addr]) == []


def test_extract_ip_addresses_valid_inet() -> None:
    addr = {"family": "inet", "local": "192.0.2.1", "prefixlen": 24, "scope": "global"}
    result = _extract_ip_addresses([addr])
    assert result == ["192.0.2.1/24"]


def test_extract_ip_addresses_skips_empty_local() -> None:
    addr = {"family": "inet", "local": "  ", "prefixlen": 24, "scope": "global"}
    assert _extract_ip_addresses([addr]) == []


# ── _collect_network_interfaces_shell ─────────────────────────────────────────


def _make_runner(responses: dict[str, str]) -> ssh_runner_mod.Runner:
    runner = MagicMock(spec=ssh_runner_mod.Runner)
    runner.run.side_effect = lambda cmd: responses.get(cmd, "")
    return runner


def test_collect_network_interfaces_shell_empty_output() -> None:
    runner = _make_runner({"(command -v ip >/dev/null 2>&1 && ip -j address show) || true": ""})
    result = _collect_network_interfaces_shell(runner)
    assert result == []


def test_collect_network_interfaces_shell_invalid_json() -> None:
    runner = _make_runner({"(command -v ip >/dev/null 2>&1 && ip -j address show) || true": "not json {"})
    result = _collect_network_interfaces_shell(runner)
    assert result == []


def test_collect_network_interfaces_shell_non_list_json() -> None:
    runner = _make_runner({"(command -v ip >/dev/null 2>&1 && ip -j address show) || true": '{"not": "a list"}'})
    result = _collect_network_interfaces_shell(runner)
    assert result == []


def test_collect_network_interfaces_shell_valid() -> None:
    data = [
        {
            "ifname": "eth0",
            "addr_info": [{"family": "inet", "local": "192.0.2.1", "prefixlen": 24, "scope": "global"}],
        }
    ]
    runner = _make_runner({"(command -v ip >/dev/null 2>&1 && ip -j address show) || true": json.dumps(data)})
    result = _collect_network_interfaces_shell(runner)
    assert len(result) == 1
    assert result[0].name == "eth0"


def test_collect_network_interfaces_shell_skips_non_dict_items() -> None:
    data = ["not-a-dict", {"ifname": "eth0", "addr_info": []}]
    runner = _make_runner({"(command -v ip >/dev/null 2>&1 && ip -j address show) || true": json.dumps(data)})
    result = _collect_network_interfaces_shell(runner)
    assert result == []


def test_collect_network_interfaces_shell_skips_empty_ifname() -> None:
    data = [{"ifname": "", "addr_info": []}]
    runner = _make_runner({"(command -v ip >/dev/null 2>&1 && ip -j address show) || true": json.dumps(data)})
    result = _collect_network_interfaces_shell(runner)
    assert result == []


def test_collect_network_interfaces_shell_skips_excluded_iface() -> None:
    data = [
        {
            "ifname": "docker0",
            "addr_info": [{"family": "inet", "local": "172.17.0.1", "prefixlen": 16, "scope": "global"}],
        }
    ]
    runner = _make_runner({"(command -v ip >/dev/null 2>&1 && ip -j address show) || true": json.dumps(data)})
    result = _collect_network_interfaces_shell(runner)
    assert result == []


# ── _parse_lscpu_json ─────────────────────────────────────────────────────────


def test_parse_lscpu_json_empty_returns_empty() -> None:
    assert _parse_lscpu_json("") == {}


def test_parse_lscpu_json_invalid_json_returns_empty() -> None:
    assert _parse_lscpu_json("not json") == {}


def test_parse_lscpu_json_non_dict_returns_empty() -> None:
    assert _parse_lscpu_json("[1, 2]") == {}


def test_parse_lscpu_json_missing_lscpu_key_returns_empty() -> None:
    assert _parse_lscpu_json('{"other": []}') == {}


def test_parse_lscpu_json_lscpu_non_list_returns_empty() -> None:
    assert _parse_lscpu_json('{"lscpu": "not-a-list"}') == {}


def test_parse_lscpu_json_valid() -> None:
    data = {"lscpu": [{"field": "Model name:", "data": "Intel Xeon"}]}
    result = _parse_lscpu_json(json.dumps(data))
    assert result["Model name"] == "Intel Xeon"


def test_parse_lscpu_json_skips_non_dict_rows() -> None:
    data = {"lscpu": ["not-a-dict", {"field": "Model name:", "data": "CPU X"}]}
    result = _parse_lscpu_json(json.dumps(data))
    assert result.get("Model name") == "CPU X"


def test_parse_lscpu_json_skips_non_string_field_or_data() -> None:
    data = {"lscpu": [{"field": 42, "data": "val"}, {"field": "Model name:", "data": 99}]}
    result = _parse_lscpu_json(json.dumps(data))
    assert result == {}


# ── _collect_platform ─────────────────────────────────────────────────────────


def test_collect_platform_returns_pretty_name() -> None:
    runner = MagicMock(spec=ssh_runner_mod.Runner)
    runner.run.return_value = 'ID=ubuntu\nPRETTY_NAME="Ubuntu 24.04"\n'
    result = _collect_platform(runner)
    assert result == "Ubuntu 24.04"


def test_collect_platform_returns_none_when_not_found() -> None:
    runner = MagicMock(spec=ssh_runner_mod.Runner)
    runner.run.return_value = ""
    result = _collect_platform(runner)
    assert result is None


# ── _collect_kernel_release ───────────────────────────────────────────────────


def test_collect_kernel_release_returns_stripped() -> None:
    runner = MagicMock(spec=ssh_runner_mod.Runner)
    runner.run.return_value = "6.8.0-99-generic\n"
    assert _collect_kernel_release(runner) == "6.8.0-99-generic"


def test_collect_kernel_release_returns_none_on_empty() -> None:
    runner = MagicMock(spec=ssh_runner_mod.Runner)
    runner.run.return_value = "  "
    assert _collect_kernel_release(runner) is None


# ── _collect_memory_gb ────────────────────────────────────────────────────────


def test_collect_memory_gb_returns_gb() -> None:
    runner = MagicMock(spec=ssh_runner_mod.Runner)
    runner.run.return_value = "MemTotal:       16384000 kB\n"
    result = _collect_memory_gb(runner)
    assert isinstance(result, int)


def test_collect_memory_gb_returns_none_on_missing() -> None:
    runner = MagicMock(spec=ssh_runner_mod.Runner)
    runner.run.return_value = ""
    assert _collect_memory_gb(runner) is None


# ── _collect_gpus ─────────────────────────────────────────────────────────────


def test_collect_gpus_returns_matching_lines() -> None:
    runner = MagicMock(spec=ssh_runner_mod.Runner)
    runner.run.return_value = "00:02.0 VGA compatible controller: Intel UHD\n00:03.0 Audio device: Intel HD Audio\n"
    result = _collect_gpus(runner)
    assert len(result) == 1
    assert "VGA compatible controller" in result[0]


# ── _parse_lsblk_disk_line ────────────────────────────────────────────────────


def test_parse_lsblk_disk_line_empty_returns_none() -> None:
    assert _parse_lsblk_disk_line("") is None


def test_parse_lsblk_disk_line_header_returns_none() -> None:
    assert _parse_lsblk_disk_line("NAME SIZE MODEL TYPE") is None


def test_parse_lsblk_disk_line_non_disk_returns_none() -> None:
    assert _parse_lsblk_disk_line("sda1  50G  part") is None


def test_parse_lsblk_disk_line_too_few_parts_returns_none() -> None:
    assert _parse_lsblk_disk_line("sda disk") is None


def test_parse_lsblk_disk_line_valid_with_model() -> None:
    result = _parse_lsblk_disk_line("sda  1T  Samsung SSD  disk")
    assert result == "sda 1T Samsung SSD"


def test_parse_lsblk_disk_line_valid_whitespace_model_becomes_unknown() -> None:
    # parts[2:-1] strips to empty string → "unknown"
    result = _parse_lsblk_disk_line("sda  1T     disk")
    # len("sda 1T disk".split()) == 3, so < 4 guard returns None
    # The "unknown" branch is unreachable through normal lsblk output.
    assert result is None


# ── _collect_storage ──────────────────────────────────────────────────────────


def test_collect_storage_parses_disk_lines() -> None:
    runner = MagicMock(spec=ssh_runner_mod.Runner)
    runner.run.return_value = "NAME  SIZE  MODEL         TYPE\nsda   1T    Samsung SSD   disk\n"
    result = _collect_storage(runner)
    assert result == ["sda 1T Samsung SSD"]


# ── _parse_snap_name ──────────────────────────────────────────────────────────


def test_parse_snap_name_header_returns_none() -> None:
    assert _parse_snap_name("Name  Version  Rev") is None


def test_parse_snap_name_empty_returns_none() -> None:
    assert _parse_snap_name("") is None


def test_parse_snap_name_valid() -> None:
    assert _parse_snap_name("core  16-2.63  16928") == "core"


# ── _collect_software ─────────────────────────────────────────────────────────


def test_collect_software_returns_tuples() -> None:
    responses = {
        "(command -v apt-mark >/dev/null 2>&1 && apt-mark showmanual) || true": "htop\nnmap\n",
        "(command -v snap >/dev/null 2>&1 && snap list) || true": "Name  Ver\ncore  16-2.63\n",
        "(docker --version) 2>/dev/null || true": "Docker version 27.0.0",
        "(docker compose version) 2>/dev/null || true": "",
        "(containerd --version) 2>/dev/null || true": "",
        "(podman --version) 2>/dev/null || true": "",
    }
    runner = _make_runner(responses)
    apt_manual, snaps, other = _collect_software(runner)
    assert "htop" in apt_manual
    assert "nmap" in apt_manual
    assert "core" in snaps
    assert any("Docker" in item for item in other)


# ── _collect_cpu ─────────────────────────────────────────────────────────────


def test_collect_cpu_with_cores_total() -> None:
    data = {
        "lscpu": [
            {"field": "Model name:", "data": "Intel Xeon"},
            {"field": "CPU(s):", "data": "8"},
            {"field": "Core(s):", "data": "4"},
        ]
    }
    runner = MagicMock(spec=ssh_runner_mod.Runner)
    runner.run.return_value = json.dumps(data)
    model, cores, threads = _collect_cpu(runner)
    assert model == "Intel Xeon"
    assert cores == 4
    assert threads == 8


def test_collect_cpu_with_cores_per_socket() -> None:
    data = {
        "lscpu": [
            {"field": "Model name:", "data": "AMD EPYC"},
            {"field": "CPU(s):", "data": "32"},
            {"field": "Core(s) per socket:", "data": "16"},
            {"field": "Socket(s):", "data": "2"},
        ]
    }
    runner = MagicMock(spec=ssh_runner_mod.Runner)
    runner.run.return_value = json.dumps(data)
    model, cores, threads = _collect_cpu(runner)
    assert model == "AMD EPYC"
    assert cores == 32
    assert threads == 32


# ── collect_inventory ─────────────────────────────────────────────────────────


def test_collect_inventory_full_shell_path(tmp_path: Path) -> None:
    ip_data = [
        {
            "ifname": "eth0",
            "addr_info": [{"family": "inet", "local": "192.0.2.1", "prefixlen": 24, "scope": "global"}],
        }
    ]
    lscpu_data = {"lscpu": [{"field": "Model name:", "data": "Test CPU"}]}

    def fake_run(cmd: str) -> str:
        if "hostname" in cmd:
            return "test-host"
        if "os-release" in cmd:
            return 'PRETTY_NAME="Ubuntu 24.04"'
        if "uname" in cmd:
            return "6.8.0"
        if "ip -j" in cmd:
            return json.dumps(ip_data)
        if "lscpu" in cmd:
            return json.dumps(lscpu_data)
        if "meminfo" in cmd:
            return "MemTotal:       8192000 kB"
        if "lspci" in cmd:
            return "00:02.0 VGA compatible controller: Intel UHD"
        if "lsblk" in cmd:
            return "NAME  SIZE  MODEL  TYPE\nsda   1T    SSD    disk\n"
        if "apt-mark" in cmd:
            return "htop"
        if "snap list" in cmd:
            return ""
        return ""

    runner = MagicMock(spec=ssh_runner_mod.Runner)
    runner.run.side_effect = fake_run
    result = collect_inventory(runner)

    assert result.hostname == "test-host"
    assert result.platform == "Ubuntu 24.04"
    assert result.kernel_release == "6.8.0"


# ── _classify_host_error ──────────────────────────────────────────────────────


def test_classify_host_error_alive_failed() -> None:
    responded, code, detail = _classify_host_error("alive test failed: Connection refused")
    assert responded is False
    assert code == "INV-SSH-ALIVE-FAILED"
    assert "Connection refused" in detail


def test_classify_host_error_host_key() -> None:
    responded, code, _ = _classify_host_error("Host key verification failed.")
    assert responded is True
    assert code == "INV-SSH-HOSTKEY"


def test_classify_host_error_cmd_failed() -> None:
    responded, code, _ = _classify_host_error("Command failed (255): ssh ...")
    assert responded is True
    assert code == "INV-SSH-CMD-FAILED"


def test_classify_host_error_remote_probe_failed() -> None:
    responded, code, _ = _classify_host_error("remote python probe failed")
    assert responded is True
    assert code == "INV-REMOTE-PROBE-FAILED"


def test_classify_host_error_json_decode() -> None:
    responded, code, _ = _classify_host_error("JSON decode error")
    assert responded is True
    assert code == "INV-REMOTE-PROBE-PARSE"


def test_classify_host_error_nodes_yml_update() -> None:
    responded, code, _ = _classify_host_error("nodes.yml update failed")
    assert responded is True
    assert code == "INV-NODES-YML-UPDATE"


def test_classify_host_error_unknown() -> None:
    responded, code, detail = _classify_host_error("some random error")
    assert responded is True
    assert code == "INV-UNKNOWN"
    assert detail == "some random error"


def test_classify_host_error_empty_string() -> None:
    _, code, detail = _classify_host_error("")
    assert code == "INV-UNKNOWN"
    assert detail == "Unknown error"


# ── _steps_for_remote_python / _steps_for_shell ───────────────────────────────


def test_steps_for_remote_python_dry_run() -> None:
    steps = _steps_for_remote_python(dry_run=True)
    assert "generate report" not in steps
    assert "generate nodes.md" not in steps


def test_steps_for_remote_python_not_dry_run() -> None:
    steps = _steps_for_remote_python(dry_run=False)
    assert "generate report" in steps
    assert "generate nodes.md" in steps


def test_steps_for_shell_dry_run() -> None:
    steps = _steps_for_shell(dry_run=True)
    assert "generate report" not in steps
    assert "hostname" in steps


def test_steps_for_shell_not_dry_run() -> None:
    steps = _steps_for_shell(dry_run=False)
    assert "generate report" in steps
    assert "generate nodes.md" in steps


# ── _print_update_status ──────────────────────────────────────────────────────


def _make_update_result(
    *,
    created: bool = False,
    node_created: bool = False,
    node_changed: bool = False,
    changed: bool = False,
) -> UpdateResult:
    return UpdateResult(
        rendered="",
        changed=changed,
        created=created,
        node_created=node_created,
        node_changed=node_changed,
    )


def _make_report_result(*, created: bool = False, changed: bool = False) -> object:
    class _FakeReportResult:
        pass

    result = _FakeReportResult()
    result.created = created  # type: ignore[attr-defined]
    result.changed = changed  # type: ignore[attr-defined]
    return result


def test_print_update_status_created(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    result = _make_update_result(created=True, changed=True)
    report_result = _make_report_result(created=True)
    _print_update_status(
        nodes_yml_path=tmp_path / "nodes.yml",
        report_jsonc_path=tmp_path / "report.jsonc",
        hostname="myhost",
        result=result,
        report_result=report_result,
    )
    out = capsys.readouterr().out
    assert "created nodes.yml" in out
    assert "Created report" in out


def test_print_update_status_node_created(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    result = _make_update_result(node_created=True, changed=True)
    report_result = _make_report_result(changed=True)
    _print_update_status(
        nodes_yml_path=tmp_path / "nodes.yml",
        report_jsonc_path=tmp_path / "report.jsonc",
        hostname="myhost",
        result=result,
        report_result=report_result,
    )
    out = capsys.readouterr().out
    assert "created node entry" in out
    assert "Updated report" in out


def test_print_update_status_node_changed(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    result = _make_update_result(node_changed=True, changed=True)
    report_result = _make_report_result()
    _print_update_status(
        nodes_yml_path=tmp_path / "nodes.yml",
        report_jsonc_path=tmp_path / "report.jsonc",
        hostname="myhost",
        result=result,
        report_result=report_result,
    )
    out = capsys.readouterr().out
    assert "updated node entry" in out
    assert "No changes for report" in out


def test_print_update_status_changed_non_node(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    result = _make_update_result(changed=True)
    report_result = _make_report_result()
    _print_update_status(
        nodes_yml_path=tmp_path / "nodes.yml",
        report_jsonc_path=tmp_path / "report.jsonc",
        hostname="myhost",
        result=result,
        report_result=report_result,
    )
    out = capsys.readouterr().out
    assert "non-node change" in out


def test_print_update_status_no_changes(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    result = _make_update_result()
    report_result = _make_report_result()
    _print_update_status(
        nodes_yml_path=tmp_path / "nodes.yml",
        report_jsonc_path=tmp_path / "report.jsonc",
        hostname="myhost",
        result=result,
        report_result=report_result,
    )
    out = capsys.readouterr().out
    assert "no changes" in out


# ── collect_inventory with progress ──────────────────────────────────────────


def _make_full_shell_runner() -> ssh_runner_mod.Runner:
    ip_data = [
        {
            "ifname": "eth0",
            "addr_info": [{"family": "inet", "local": "192.0.2.1", "prefixlen": 24, "scope": "global"}],
        }
    ]
    lscpu_data = {"lscpu": [{"field": "Model name:", "data": "Test CPU"}]}

    def fake_run(cmd: str) -> str:
        if "hostname" in cmd:
            return "test-host"
        if "os-release" in cmd:
            return 'PRETTY_NAME="Ubuntu 24.04"'
        if "uname" in cmd:
            return "6.8.0"
        if "ip -j" in cmd:
            return json.dumps(ip_data)
        if "lscpu" in cmd:
            return json.dumps(lscpu_data)
        if "meminfo" in cmd:
            return "MemTotal:       8192000 kB"
        if "lspci" in cmd:
            return ""
        if "lsblk" in cmd:
            return ""
        if "apt-mark" in cmd:
            return ""
        if "snap list" in cmd:
            return ""
        return ""

    runner = MagicMock(spec=ssh_runner_mod.Runner)
    runner.run.side_effect = fake_run
    return runner


def test_collect_inventory_with_progress_advances_all_steps(capsys: pytest.CaptureFixture[str]) -> None:
    from scripts.inventory.reporting import Progress

    runner = _make_full_shell_runner()
    steps = ["hostname", "platform", "kernel", "network", "cpu", "memory", "gpu", "storage", "software"]
    prog = Progress(steps=steps, enabled=True)
    result = collect_inventory(runner, progress=prog)

    assert result.hostname == "test-host"
    out = capsys.readouterr().out
    assert "hostname" in out
    assert "software" in out


# ── _collect_one_and_update_nodes_yml shell mode ──────────────────────────────


def test_collect_one_shell_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    nodes_yml = tmp_path / "nodes.yml"
    runner = _make_full_shell_runner()

    monkeypatch.setattr(ssh_runner_mod, "Runner", lambda *args, **kwargs: runner)

    inv, result, _prog = _collect_one_and_update_nodes_yml(
        host=None,
        user="root",
        port=None,
        identity_file=None,
        remote_mode="shell",
        remote_python_sudo=False,
        nodes_yml_path=nodes_yml,
        dry_run=True,
        include_output_steps=False,
    )

    assert inv.hostname == "test-host"
    assert result.rendered != ""


# ── _collect_all_hosts raises when continue_on_error=False ───────────────────


def test_collect_all_hosts_raises_when_continue_on_error_false(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    nodes_yml = tmp_path / "nodes.yml"

    def fake_collect_one(**kwargs) -> None:
        raise RuntimeError("Command failed (255): ssh ...")

    monkeypatch.setattr(
        "scripts.inventory.collect_node_inventory._collect_one_and_update_nodes_yml",
        fake_collect_one,
    )

    targets = [HostTarget(hostname="bad-host", user="root")]

    with pytest.raises(RuntimeError, match="Command failed"):
        _collect_all_hosts(
            targets=targets,
            port=None,
            identity_file=None,
            remote_mode="python",
            remote_python_sudo=False,
            nodes_yml_path=nodes_yml,
            continue_on_error=False,
        )
