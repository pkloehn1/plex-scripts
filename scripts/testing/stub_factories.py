"""Test stub factories for git and docker command runners.

Provides :func:`make_git_runner` and :func:`make_docker_runner_success`
for use in test suites that need deterministic command runner stubs.
"""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Callable
from pathlib import Path

from scripts.common.git_runner import GitResult

# Stable fake manifest bytes and their digest — used by make_docker_runner_success
# so that local and remote digests match (simulating a fresh image).
FAKE_MANIFEST_BYTES = b'{"fake": "manifest"}'
FAKE_MANIFEST_DIGEST = "sha256:" + hashlib.sha256(FAKE_MANIFEST_BYTES).hexdigest()


def make_git_runner(
    *,
    head_ref: str = "refs/remotes/origin/main",
    ref_exists: bool = True,
    error: str | None = None,
) -> Callable[[list[str]], GitResult]:
    """Create a git runner stub for tests."""

    def run_git(args: list[str], *, cwd: Path | None = None) -> GitResult:
        if error:
            return GitResult(127, "", error)
        if args[:2] == ["symbolic-ref", "refs/remotes/origin/HEAD"]:
            return GitResult(0, f"{head_ref}\n", "")
        if args[:3] == ["show-ref", "--verify", "--quiet"]:
            return GitResult(0 if ref_exists else 1, "", "")
        return GitResult(1, "", "unexpected git args")

    return run_git


def _match_freshness_cmd(
    cmd: list[str],
    *,
    manifest_bytes: bytes,
    manifest_digest: str,
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes] | None:
    """Dispatch freshness-check docker commands (image inspect, buildx, pull, rmi)."""
    if cmd[1:3] == ["image", "inspect"]:
        if any("RepoDigests" in arg for arg in cmd):
            image_name = cmd[-1]
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{image_name}@{manifest_digest}", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="sha256:localid", stderr="")
    if cmd[1:4] == ["buildx", "imagetools", "inspect"]:
        result: subprocess.CompletedProcess[bytes] = subprocess.CompletedProcess(
            cmd, 0, stdout=manifest_bytes, stderr=b""
        )
        return result
    if cmd[1:2] == ["pull"]:
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    if cmd[1:2] == ["rmi"]:
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    return None


def make_docker_runner_success(
    *,
    seen: list[list[str]] | None = None,
    manifest_bytes: bytes = FAKE_MANIFEST_BYTES,
    manifest_digest: str = FAKE_MANIFEST_DIGEST,
) -> Callable[..., subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]]:
    """Create a docker runner stub that succeeds for version/run/freshness.

    By default, local and remote digests match (fresh image), so the
    freshness check skips pulling.  Override *manifest_bytes* or
    *manifest_digest* to simulate stale/missing scenarios.
    """

    def run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
        if seen is not None:
            seen.append(cmd)
        if cmd[:2] == ["docker", "version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if cmd[:2] == ["docker", "run"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        freshness = _match_freshness_cmd(cmd, manifest_bytes=manifest_bytes, manifest_digest=manifest_digest)
        if freshness is not None:
            return freshness
        raise AssertionError(f"Unexpected command: {cmd}")

    return run
