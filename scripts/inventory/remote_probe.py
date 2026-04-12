"""Remote node inventory probe — executed on target hosts via SSH stdin.

This script is sent over SSH as stdin to ``python3 -`` (or ``sudo -n python3 -``)
by :mod:`scripts.inventory.collect_node_inventory`.  It collects hardware and
software inventory from the remote system and writes a single JSON object to
stdout.

**Constraints:**
- Must use only the Python standard library (no third-party dependencies).
- Must NOT import anything from ``scripts.*`` (it runs on remote nodes that do
    not have this repository).
- Must remain syntactically valid as a standalone script.
"""

import json
import re
import subprocess
import sys

_VIRTUAL_IFACE_RE = re.compile(r"^(veth|br-|docker|virbr|cni|flannel|calico|podman)")
_GPU_DEVICE_RE = re.compile(r"VGA compatible controller|3D controller|Display controller")


def _run(cmd):
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout


def _first_match(text, pattern):
    match = re.search(pattern, text, flags=re.MULTILINE)
    if not match:
        return None
    value = match.group(1).strip()
    return value or None


def _first_int(text):
    if text is None:
        return None
    match = re.search(r"(\d+)", str(text))
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _dedupe(values):
    seen = set()
    out = []
    for item in values:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _is_virtual_interface(name):
    return name == "lo" or _VIRTUAL_IFACE_RE.match(name)


def _parse_address(addr):
    """Return a CIDR string from an ip-address-show addr_info entry, or None."""
    if not isinstance(addr, dict):
        return None
    if addr.get("family") not in ("inet", "inet6"):
        return None
    local = addr.get("local")
    if not isinstance(local, str) or not local.strip():
        return None
    if addr.get("scope") == "link":
        return None
    prefixlen = addr.get("prefixlen")
    if not isinstance(prefixlen, int):
        return None
    return f"{local.strip()}/{prefixlen}"


def _parse_interface(item):
    """Return an interface dict from an ip-address-show entry, or None."""
    if not isinstance(item, dict):
        return None
    name = item.get("ifname")
    if not isinstance(name, str) or not name.strip():
        return None
    name = name.strip()
    if _is_virtual_interface(name):
        return None
    addr_info = item.get("addr_info")
    if not isinstance(addr_info, list):
        return None
    addresses = sorted(_dedupe([cidr for addr in addr_info if (cidr := _parse_address(addr))]))
    if not addresses:
        return None
    return {"name": name, "addresses": addresses}


def _collect_network_interfaces():
    raw = _run(
        [
            "bash",
            "-lc",
            "(command -v ip >/dev/null 2>&1 && ip -j address show) || true",
        ]
    )
    if not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    interfaces = [iface for item in parsed if (iface := _parse_interface(item))]
    interfaces.sort(key=lambda iface: iface.get("name") or "")
    return interfaces


hostname = _run(["hostname"]).strip() or None

os_release = _run(["bash", "-lc", "cat /etc/os-release 2>/dev/null || true"])
platform = _first_match(os_release, r"^PRETTY_NAME=(?:\"|')?(.*?)(?:\"|')?$")

kernel_release = _run(["uname", "-r"]).strip() or None

network_interfaces = _collect_network_interfaces()

lscpu_raw = _run(["bash", "-lc", "(command -v lscpu >/dev/null 2>&1 && lscpu -J) || true"])
cpu_model = None
cpu_threads = None
cpu_cores = None
try:
    parsed = json.loads(lscpu_raw.strip() or "{}")
    rows = parsed.get("lscpu") or []
    fields = {}
    for row in rows:
        field = row.get("field")
        data = row.get("data")
        if isinstance(field, str) and isinstance(data, str):
            key = field.strip().rstrip(":").strip()
            val = data.strip()
            if key and val:
                fields[key] = val
    cpu_model = fields.get("Model name")
    cpu_threads = _first_int(fields.get("CPU(s)"))
    cores_total = _first_int(fields.get("Core(s)"))
    if cores_total is not None:
        cpu_cores = cores_total
    else:
        cps = _first_int(fields.get("Core(s) per socket"))
        sockets = _first_int(fields.get("Socket(s)"))
        if cps is not None and sockets is not None:
            cpu_cores = cps * sockets
except Exception:
    # Inventory collection is best-effort; if lscpu parsing fails, leave CPU fields as None.
    pass

meminfo = _run(["bash", "-lc", "cat /proc/meminfo 2>/dev/null || true"])
mem_kb = _first_int(_first_match(meminfo, r"^MemTotal:\s+(\d+)\s+kB"))
memory_gb = None
if mem_kb is not None:
    memory_gb = round((mem_kb * 1024) / (1024**3))

lspci_out = _run(["bash", "-lc", "(command -v lspci >/dev/null 2>&1 && lspci) || true"])
gpus = []
for line in lspci_out.splitlines():
    stripped = line.strip()
    if stripped and _GPU_DEVICE_RE.search(line):
        gpus.append(stripped)

lsblk_out = _run(["bash", "-lc", "(command -v lsblk >/dev/null 2>&1 && lsblk -d -o NAME,SIZE,MODEL,TYPE) || true"])
storage = []
for line in lsblk_out.splitlines():
    if line.strip().startswith("NAME"):
        continue
    if not line.strip():
        continue
    parts = line.split()
    if len(parts) < 4:
        continue
    name, size, *rest = parts
    device_type = rest[-1]
    model = " ".join(rest[:-1]).strip() or "unknown"
    if device_type != "disk":
        continue
    storage.append(f"{name} {size} {model}")

apt_manual_raw = _run(["bash", "-lc", "(command -v apt-mark >/dev/null 2>&1 && apt-mark showmanual) || true"])
apt_manual = [line.strip() for line in apt_manual_raw.splitlines() if line.strip()]

snaps_raw = _run(["bash", "-lc", "(command -v snap >/dev/null 2>&1 && snap list) || true"])
snaps = []
for line in snaps_raw.splitlines():
    if line.strip().startswith("Name"):
        continue
    cols = line.split()
    if cols:
        snaps.append(cols[0])

other = []
for cmd in [
    "docker --version",
    "docker compose version",
    "containerd --version",
    "podman --version",
]:
    out = _run(["bash", "-lc", f"({cmd}) 2>/dev/null || true"]).strip()
    if out:
        other.append(out)

payload = {
    "hostname": hostname,
    "platform": platform,
    "kernel_release": kernel_release,
    "network_interfaces": network_interfaces,
    "cpu_model": cpu_model,
    "cpu_cores": cpu_cores,
    "cpu_threads": cpu_threads,
    "memory_gb": memory_gb,
    "gpus": _dedupe(gpus),
    "storage": _dedupe(storage),
    "apt_manual": _dedupe(apt_manual),
    "snaps": _dedupe(snaps),
    "other": _dedupe(other),
}

sys.stdout.write(json.dumps(payload, ensure_ascii=False))
