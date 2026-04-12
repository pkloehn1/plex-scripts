#!/usr/bin/env python3
"""Run Super-Linter locally.

Design goals:
- Works on Linux without requiring PowerShell.
- Supports hardened Linux hosts where Docker is sudo-only via SUPER_LINTER_DOCKER_CMD.

Execution model:
- Linux/macOS: runs the Super-Linter image as a one-shot container (`docker run --rm`).
- Windows: runs the Super-Linter image as a one-shot container (`docker run --rm`).

Environment variables:
- SUPER_LINTER_DOCKER_CMD: Docker command to invoke (default: "docker").
    Example on sudo-only hosts: "sudo -n docker"
- SUPER_LINTER_IMAGE: Super-Linter image tag to run.
- SUPER_LINTER_PULL_POLICY: Image freshness policy (default: "always").
    Valid values: "always" | "missing".
    "always": compare local digest to registry; pull only when stale, remove old image.
    "missing": skip freshness check; only pull if the image is absent locally.
"""

from __future__ import annotations

import hashlib
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from scripts.common import git_runner

try:
    import fcntl  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


SUPER_LINTER_IMAGE_DEFAULT = "ghcr.io/super-linter/super-linter:v8"
_CONTAINER_WORKSPACE = "/workspace"


def _resolve_super_linter_image() -> str:
    override = os.environ.get("SUPER_LINTER_IMAGE", "").strip()
    if override:
        if "super-linter:slim-v8" in override:
            return SUPER_LINTER_IMAGE_DEFAULT
        return override
    return SUPER_LINTER_IMAGE_DEFAULT


def _resolve_default_branch(repo_root: Path) -> str:
    override = os.environ.get("SUPER_LINTER_DEFAULT_BRANCH", "").strip()
    if override:
        return override

    result = git_runner.run_git(
        ["symbolic-ref", "refs/remotes/origin/HEAD"],
        cwd=repo_root,
    )
    if result.returncode == 0:
        ref = result.stdout.strip()
        if ref.startswith("refs/remotes/"):
            return ref.replace("refs/remotes/", "", 1)

    return "main"


def _candidate_refs_for(default_branch: str) -> list[str]:
    if default_branch.startswith("refs/"):
        return [default_branch]

    candidates = []
    if "/" in default_branch:
        candidates.append(f"refs/remotes/{default_branch}")
    candidates.append(f"refs/heads/{default_branch}")
    return candidates


def _git_ref_exists(repo_root: Path, default_branch: str) -> bool:
    for ref in _candidate_refs_for(default_branch):
        result = git_runner.run_git(
            ["show-ref", "--verify", "--quiet", ref],
            cwd=repo_root,
        )
        if result.returncode == 0:
            return True
    return False


def _maybe_append_default_filter_excludes(env_pairs: list[tuple[str, str]], *, image: str) -> None:
    # Local development commonly uses a repo-managed Python virtualenv at .venv/.
    # Super-Linter's JSCPD validator will scan it by default, causing noisy and
    # slow failures that do not reflect CI behavior.
    #
    # Keep the exception tightly scoped:
    # - Only apply for the exact Super-Linter image we run locally.
    # - Only set it if the operator hasn't already specified FILTER_REGEX_EXCLUDE.
    if image != SUPER_LINTER_IMAGE_DEFAULT:
        return
    if os.environ.get("FILTER_REGEX_EXCLUDE"):
        return

    # Keep this list small and limited to dev-only artifacts.
    default_excluded_dirs = (
        r"\.venv",
        r"\.tox",
        r"\.pytest_cache",
        r"\.mypy_cache",
        r"\.ruff_cache",
    )
    pattern = r"(^|/)({})/".format("|".join(default_excluded_dirs))
    env_pairs.append(("FILTER_REGEX_EXCLUDE", pattern))


def _maybe_set_default_jscpd_config_file(env_pairs: list[tuple[str, str]], *, image: str, repo_root: Path) -> None:
    if image != SUPER_LINTER_IMAGE_DEFAULT:
        return
    if os.environ.get("JSCPD_LINTER_RULES") or os.environ.get("JSCPD_CONFIG_FILE"):
        return

    config_path = repo_root / ".github" / "linters" / ".jscpd.json"
    if not config_path.is_file():
        return

    # Super-Linter expects JSCPD config via JSCPD_LINTER_RULES.
    # Point it at the tracked config inside the container workspace.
    env_pairs.append(("JSCPD_LINTER_RULES", f"{_CONTAINER_WORKSPACE}/.github/linters/.jscpd.json"))


def _repo_root() -> Path:
    from scripts.common.paths import repo_root

    return repo_root()


def _run(cmd: list[str], *, cwd: Path) -> int:
    completed = subprocess.run(cmd, cwd=str(cwd), check=False)
    return int(completed.returncode)


def _is_docker_permission_denied(stderr: str) -> bool:
    stderr_lower = (stderr or "").lower()
    patterns = (
        "got permission denied while trying to connect to the docker daemon socket",
        "permission denied",
        "connect: permission denied",
        "dial unix",
        "/var/run/docker.sock",
    )
    return any(pattern in stderr_lower for pattern in patterns)


def _is_sudo_auth_required(stderr: str) -> bool:
    stderr_lower = (stderr or "").lower()
    patterns = (
        "sudo: a password is required",
        "a password is required",
        "no tty present and no askpass program specified",
        "a terminal is required to read the password",
        "you must have a tty",
    )
    return any(pattern in stderr_lower for pattern in patterns)


def _try_sudo_docker_cmd(repo_root: Path) -> list[str] | None:
    if sys.platform.startswith("win"):
        return None

    sudo_version_proc = subprocess.run(
        ["sudo", "-n", "docker", "version"],
        cwd=str(repo_root),
        check=False,
        text=True,
        capture_output=True,
    )
    if sudo_version_proc.returncode == 0:
        return ["sudo", "-n", "docker"]
    return None


def _probe_docker_version(repo_root: Path, docker_cmd: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            [*docker_cmd, "version"],
            cwd=str(repo_root),
            check=False,
            text=True,
            capture_output=True,
        )
    except FileNotFoundError:
        return None


def _resolve_usable_docker_cmd(repo_root: Path, docker_cmd: list[str]) -> tuple[list[str] | None, int]:
    version_proc = _probe_docker_version(repo_root, docker_cmd)
    if version_proc is None:
        sys.stderr.write(
            "Docker command not found for Super-Linter.\n"
            f"Attempted command: {' '.join(docker_cmd)}\n"
            "Fix:\n"
            "  - Install Docker and ensure it is on PATH\n"
            "  - Or set SUPER_LINTER_DOCKER_CMD to your docker invocation\n"
        )
        return None, 127
    if version_proc.returncode == 0:
        return docker_cmd, 0

    stderr_raw = version_proc.stderr or ""

    if docker_cmd and docker_cmd[0] == "sudo" and _is_sudo_auth_required(stderr_raw):
        sys.stderr.write(
            "Docker requires sudo on this host, but sudo is not authorized for non-interactive use in this session.\n\n"
            "Fix:\n"
            "  - Run `sudo -v` in a terminal to refresh the sudo token, then retry.\n\n"
            "Note: pre-commit cannot prompt for a sudo password.\n"
        )
        return None, int(version_proc.returncode)

    if docker_cmd and docker_cmd[0] != "sudo" and _is_docker_permission_denied(stderr_raw):
        sudo_docker_cmd = _try_sudo_docker_cmd(repo_root)
        if sudo_docker_cmd is not None:
            return sudo_docker_cmd, 0

        sys.stderr.write(
            "Docker access denied for this user. This host appears to require sudo for Docker.\n\n"
            "Fix:\n"
            "  - Run `sudo -v` (interactive) and retry the commit immediately\n\n"
            "Note: pre-commit cannot prompt for a sudo password.\n"
        )
        return None, int(version_proc.returncode)

    sys.stderr.write(
        "Docker is not usable from this session.\n"
        "Fix:\n"
        "  - Run `sudo -v` (interactive) and retry the commit immediately\n\n"
        "Note: pre-commit cannot prompt for a sudo password.\n"
    )
    return None, int(version_proc.returncode)


def _docker_cmd() -> list[str]:
    docker_cmd_raw = os.environ.get("SUPER_LINTER_DOCKER_CMD", "docker").strip() or "docker"
    cmd = shlex.split(docker_cmd_raw)

    # If the operator uses sudo for Docker:
    # - In interactive TTY sessions, allow sudo to prompt (so the human can enter
    #   credentials).
    # - In non-interactive sessions, force -n so the hook fails fast instead of hanging.
    if cmd and cmd[0] == "sudo" and "-n" not in cmd:
        is_tty = sys.stdin.isatty() and sys.stdout.isatty() and sys.stderr.isatty()
        if not is_tty:
            cmd.insert(1, "-n")

    return cmd


def _resolve_validate_all_codebase(repo_root: Path, default_branch: str) -> str:
    validate_all = os.environ.get("SUPER_LINTER_VALIDATE_ALL_CODEBASE", "").strip()
    if validate_all:
        return validate_all.lower()

    if not _git_ref_exists(repo_root, default_branch):
        sys.stderr.write("DEFAULT_BRANCH ref not found locally; running Super-Linter against all files.\n")
        return "true"
    return "false"


def _build_env_pairs(repo_root: Path, *, image: str, default_branch: str) -> list[tuple[str, str]]:
    env_pairs: list[tuple[str, str]] = [
        ("RUN_LOCAL", "true"),
        ("GITHUB_ACTIONS", "true"),
        ("GITHUB_WORKSPACE", _CONTAINER_WORKSPACE),
        ("VALIDATE_GITHUB_ACTIONS", "true"),
        ("VALIDATE_MARKDOWN", "true"),
        ("VALIDATE_YAML", "true"),
        ("VALIDATE_JSCPD", "true"),
        ("VALIDATE_BASH", "true"),
        ("VALIDATE_BASH_EXEC", "true"),
        ("VALIDATE_SHELL_SHFMT", "true"),
        ("VALIDATE_POWERSHELL", "true"),
        ("VALIDATE_JSON", "true"),
        ("VALIDATE_JSONC", "true"),
        ("VALIDATE_EDITORCONFIG", "true"),
        ("VALIDATE_CHECKOV", "true"),
        ("CHECKOV_SKIP_PATH", "/tmp,/workspace/tmp"),
        ("VALIDATE_ENV", "true"),
        ("VALIDATE_GITLEAKS", "true"),
        ("VALIDATE_PYTHON_RUFF", "true"),
        ("VALIDATE_PYTHON_RUFF_FORMAT", "true"),
        # Ruff config is auto-discovered; avoid explicit config env vars.
        ("LINTER_RULES_PATH", ".github/linters"),
        # Super-Linter default is .markdown-lint.yml (hyphenated); our file
        # uses the markdownlint-native name .markdownlint.yml (no hyphen).
        ("MARKDOWN_CONFIG_FILE", ".markdownlint.yml"),
        ("DEFAULT_BRANCH", default_branch),
        (
            "VALIDATE_ALL_CODEBASE",
            _resolve_validate_all_codebase(repo_root, default_branch),
        ),
    ]

    _maybe_append_default_filter_excludes(env_pairs, image=image)
    _maybe_set_default_jscpd_config_file(env_pairs, image=image, repo_root=repo_root)
    return env_pairs


def _resolve_pull_policy() -> str | None:
    pull_policy = (os.environ.get("SUPER_LINTER_PULL_POLICY", "always").strip() or "always").lower()
    if pull_policy not in {"always", "missing"}:
        sys.stderr.write("Invalid SUPER_LINTER_PULL_POLICY. Expected 'always' or 'missing'.\n")
        return None
    return pull_policy


def _get_local_repo_digest(docker_cmd: list[str], image: str, *, cwd: Path) -> str | None:
    """Return the repo digest of the locally cached image (e.g. 'sha256:abc...')."""
    result = subprocess.run(
        [*docker_cmd, "image", "inspect", "--format", "{{index .RepoDigests 0}}", image],
        cwd=str(cwd),
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    raw = result.stdout.strip()
    if "@" not in raw:
        return None
    return raw.split("@", 1)[1]


def _get_remote_repo_digest(docker_cmd: list[str], image: str, *, cwd: Path) -> str | None:
    """Query the registry manifest digest without downloading layers."""
    result = subprocess.run(
        [*docker_cmd, "buildx", "imagetools", "inspect", "--raw", image],
        cwd=str(cwd),
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    return "sha256:" + hashlib.sha256(result.stdout).hexdigest()


def _get_local_image_id(docker_cmd: list[str], image: str, *, cwd: Path) -> str | None:
    """Return the local image ID, or None if not present."""
    result = subprocess.run(
        [*docker_cmd, "image", "inspect", "--format", "{{.Id}}", image],
        cwd=str(cwd),
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _pull_image(docker_cmd: list[str], image: str, *, cwd: Path) -> int:
    """Pull *image* and return the exit code."""
    completed = subprocess.run(
        [*docker_cmd, "pull", image],
        cwd=str(cwd),
        check=False,
    )
    return int(completed.returncode)


def _remove_old_image(docker_cmd: list[str], image_id: str, *, cwd: Path) -> None:
    """Remove a specific image by ID (targeted cleanup, not blanket prune)."""
    subprocess.run(
        [*docker_cmd, "rmi", image_id],
        cwd=str(cwd),
        check=False,
        capture_output=True,
    )


def _ensure_image_fresh(docker_cmd: list[str], image: str, *, cwd: Path) -> int:
    """Check local image against registry; pull only if stale or missing.

    Returns 0 on success, non-zero if the image could not be obtained.
    """
    local_digest = _get_local_repo_digest(docker_cmd, image, cwd=cwd)

    if local_digest is None:
        sys.stderr.write(f"Super-Linter image not found locally. Pulling {image}...\n")
        ret = _pull_image(docker_cmd, image, cwd=cwd)
        if ret != 0:
            sys.stderr.write(f"Failed to pull {image} (exit {ret}).\n")
            return ret
        sys.stderr.write(f"Super-Linter image pulled: {image}\n")
        return 0

    remote_digest = _get_remote_repo_digest(docker_cmd, image, cwd=cwd)

    if remote_digest is None:
        sys.stderr.write("Cannot check registry digest. Using cached image.\n")
        return 0

    if local_digest == remote_digest:
        return 0

    old_id = _get_local_image_id(docker_cmd, image, cwd=cwd)
    sys.stderr.write(f"Super-Linter image is stale. Pulling {image}...\n")
    ret = _pull_image(docker_cmd, image, cwd=cwd)
    if ret != 0:
        sys.stderr.write(f"Failed to pull {image} (exit {ret}). Using cached image.\n")
        return 0
    if old_id is not None:
        _remove_old_image(docker_cmd, old_id, cwd=cwd)
    sys.stderr.write(f"Super-Linter image updated: {image}\n")
    return 0


def _build_docker_args(
    repo_root: Path,
    *,
    env_pairs: list[tuple[str, str]],
    image: str,
    pull_policy: str,
) -> list[str]:
    args: list[str] = ["run", "--rm", "--pull", pull_policy]

    for env_key, env_value in env_pairs:
        args += ["-e", f"{env_key}={env_value}"]

    # Mount the repository into a stable, non-/tmp path inside the container.
    args += ["-v", f"{repo_root}:{_CONTAINER_WORKSPACE}"]
    args += ["-w", _CONTAINER_WORKSPACE]
    args.append(image)
    return args


def _run_docker(repo_root: Path) -> int:
    docker_cmd, ret = _resolve_usable_docker_cmd(repo_root, _docker_cmd())
    if docker_cmd is None:
        return ret

    def docker(args: list[str]) -> int:
        return _run(docker_cmd + args, cwd=repo_root)

    # Avoid concurrent runs to keep output deterministic and reduce resource spikes.
    lock_path = repo_root / ".git" / "super-linter.lock"
    lock_file = None
    if fcntl is not None and (repo_root / ".git").is_dir():
        lock_file = lock_path.open("a")
        fcntl_mod = cast(Any, fcntl)
        fcntl_mod.flock(lock_file.fileno(), fcntl_mod.LOCK_EX)

    try:
        image = _resolve_super_linter_image()
        default_branch = _resolve_default_branch(repo_root)
        env_pairs = _build_env_pairs(repo_root, image=image, default_branch=default_branch)
        pull_policy = _resolve_pull_policy()
        if pull_policy is None:
            return 2
        if pull_policy == "always":
            fresh_ret = _ensure_image_fresh(docker_cmd, image, cwd=repo_root)
            if fresh_ret != 0:
                return fresh_ret
            effective_pull = "never"
        else:
            effective_pull = pull_policy
        args = _build_docker_args(repo_root, env_pairs=env_pairs, image=image, pull_policy=effective_pull)
        return docker(args)
    finally:
        if lock_file is not None and fcntl is not None:
            fcntl_mod = cast(Any, fcntl)
            fcntl_mod.flock(lock_file.fileno(), fcntl_mod.LOCK_UN)
            lock_file.close()


def main() -> int:
    repo_root = _repo_root()
    return _run_docker(repo_root)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
