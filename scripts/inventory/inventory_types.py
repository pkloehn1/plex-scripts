from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NetworkInterface:
    name: str
    addresses: list[str]


@dataclass(frozen=True, slots=True)
class CollectedInventory:
    hostname: str
    platform: str | None
    kernel_release: str | None
    network_interfaces: list[NetworkInterface]
    cpu_model: str | None
    cpu_cores: int | None
    cpu_threads: int | None
    memory_gb: int | None
    gpus: list[str]
    storage: list[str]
    apt_manual: list[str]
    snaps: list[str]
    other: list[str]


@dataclass(frozen=True, slots=True)
class UpdateResult:
    rendered: str
    changed: bool
    created: bool
    node_created: bool
    node_changed: bool


@dataclass(frozen=True, slots=True)
class HostRunStatus:
    hostname: str
    responded: bool
    all_steps_completed: bool
    error_code: str | None
    error_detail: str | None


@dataclass(frozen=True, slots=True)
class HostTarget:
    hostname: str
    user: str
