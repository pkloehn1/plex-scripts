"""Tests for scripts.inventory.remote_probe (standalone remote collector)."""

from __future__ import annotations

from dataclasses import fields as dataclass_fields
from pathlib import Path

from scripts.inventory.inventory_types import CollectedInventory

_PROBE_PATH = Path(__file__).resolve().parents[1] / "remote_probe.py"
_PROBE_SOURCE = _PROBE_PATH.read_text()


def test_remote_probe_compiles() -> None:
    """remote_probe.py is syntactically valid Python."""
    compile(_PROBE_SOURCE, str(_PROBE_PATH), "exec")


def test_remote_probe_has_no_scripts_imports() -> None:
    """remote_probe.py must not import from scripts.* (runs on remote nodes)."""
    for line in _PROBE_SOURCE.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert "from scripts" not in stripped, f"Forbidden import: {stripped}"
        if stripped.startswith("import scripts"):
            raise AssertionError(f"Forbidden import: {stripped}")


def test_remote_probe_payload_keys_match_collected_inventory() -> None:
    """The JSON payload keys in remote_probe.py match CollectedInventory fields."""
    expected_fields = {field.name for field in dataclass_fields(CollectedInventory)}

    # Extract the payload dict keys from the source.
    in_payload = False
    payload_keys: set[str] = set()
    for line in _PROBE_SOURCE.splitlines():
        stripped = line.strip()
        if stripped.startswith("payload = {"):
            in_payload = True
            continue
        if in_payload:
            if stripped == "}":
                break
            # Lines like:  "hostname": hostname,
            if stripped.startswith('"'):
                key = stripped.split('"')[1]
                payload_keys.add(key)

    assert payload_keys, "Failed to extract any payload keys from remote_probe.py"
    assert payload_keys == expected_fields, (
        f"Payload keys differ from CollectedInventory fields.\n"
        f"  Extra in probe: {payload_keys - expected_fields}\n"
        f"  Missing from probe: {expected_fields - payload_keys}"
    )
