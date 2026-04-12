#!/usr/bin/env python3
"""Bootstrap the repo venv and dev tooling (cross-platform).

Usage:
    python -m scripts.dev.bootstrap_venv
    python3 -m scripts.dev.bootstrap_venv
    py -3 -m scripts.dev.bootstrap_venv
    python -m scripts.dev.bootstrap_venv --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Callable, Mapping
from pathlib import Path

from scripts.testing.hooks.check_git_signing import check_git_signing

EXIT_OK = 0
EXIT_FAILED = 1
VENV_DIR = ".venv"
PYPROJECT_FILE = "pyproject.toml"
STATE_FILENAME = ".bootstrap_state.json"
State = Mapping[str, object]
_REQ_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+")


def repo_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[2]


def _venv_python_candidates(repo_root: Path) -> list[Path]:
    return [
        repo_root / VENV_DIR / "bin" / "python",
        repo_root / VENV_DIR / "Scripts" / "python.exe",
    ]


def _is_executable_path(path: Path, platform: str) -> bool:
    if platform == "win32":
        return path.exists()
    return path.exists() and os.access(path, os.X_OK)


def _resolve_venv_python(repo_root: Path, platform: str) -> Path | None:
    for candidate in _venv_python_candidates(repo_root):
        if _is_executable_path(candidate, platform):
            return candidate
    return None


def resolve_system_python_cmd(platform: str, which: Callable[[str], str | None] = shutil.which) -> list[str] | None:
    if platform == "win32":
        candidates = ["python", "py"]
    else:
        candidates = ["python3", "python"]

    for candidate in candidates:
        if which(candidate):
            if candidate == "py":
                return ["py", "-3"]
            return [candidate]
    return None


def _state_file_path(repo_root: Path) -> Path:
    return repo_root / VENV_DIR / STATE_FILENAME


def _hash_file(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalize_package_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _extract_requirement_name(requirement: str) -> str | None:
    if not requirement:
        return None
    base = requirement.split(";", 1)[0].strip()
    base = base.split("@", 1)[0].strip()
    base = base.split("[", 1)[0].strip()
    match = _REQ_NAME_RE.match(base)
    return match.group(0) if match else None


def _load_dev_requirements(repo_root: Path) -> list[str]:
    pyproject_path = repo_root / PYPROJECT_FILE
    if not pyproject_path.exists():
        return []
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = data.get("project")
    if not isinstance(project, dict):
        return []
    optional_deps = project.get("optional-dependencies")
    if not isinstance(optional_deps, dict):
        return []
    dev_deps = optional_deps.get("dev")
    if not isinstance(dev_deps, list):
        return []
    names: list[str] = []
    for entry in dev_deps:
        if not isinstance(entry, str):
            continue
        name = _extract_requirement_name(entry)
        if name:
            names.append(_normalize_package_name(name))
    return sorted(set(names))


def build_desired_state(repo_root: Path) -> dict[str, str | None]:
    return {
        "pyproject_hash": _hash_file(repo_root / PYPROJECT_FILE),
        "pre_commit_config_hash": _hash_file(repo_root / ".pre-commit-config.yaml"),
    }


def load_bootstrap_state(state_path: Path) -> dict[str, str | None] | None:
    if not state_path.exists():
        return None
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return {
        "pyproject_hash": data.get("pyproject_hash"),
        "pre_commit_config_hash": data.get("pre_commit_config_hash"),
    }


def write_bootstrap_state(state_path: Path, desired_state: dict[str, str | None]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pyproject_hash": desired_state.get("pyproject_hash"),
        "pre_commit_config_hash": desired_state.get("pre_commit_config_hash"),
    }
    state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def collect_state(
    *,
    repo_root: Path,
    platform: str,
    which: Callable[[str], str | None] = shutil.which,
) -> State:
    venv_python = _resolve_venv_python(repo_root, platform)
    pyproject_present = (repo_root / PYPROJECT_FILE).exists()
    desired_state = build_desired_state(repo_root) if pyproject_present else None
    state_path = _state_file_path(repo_root)
    existing_state = load_bootstrap_state(state_path)
    pyproject_matches = bool(
        existing_state and desired_state and existing_state.get("pyproject_hash") == desired_state.get("pyproject_hash")
    )
    pre_commit_matches = bool(
        existing_state
        and desired_state
        and existing_state.get("pre_commit_config_hash") == desired_state.get("pre_commit_config_hash")
    )
    state_matches = pyproject_matches and pre_commit_matches
    return {
        "platform": platform,
        "repo_root": str(repo_root),
        "system_python": (" ".join(resolve_system_python_cmd(platform, which=which) or []) or None),
        "venv_path": str(repo_root / VENV_DIR),
        "venv_python": str(venv_python) if venv_python else None,
        "venv_exists": (repo_root / VENV_DIR).exists(),
        "pyproject_present": pyproject_present,
        "pre_commit_hook_exists": (repo_root / ".git" / "hooks" / "pre-commit").exists(),
        "state_matches": state_matches,
        "pyproject_matches": pyproject_matches,
        "pre_commit_matches": pre_commit_matches,
        "desired_state": desired_state,
        "state_path": str(state_path),
    }


def build_plan(state: State) -> list[str]:
    actions = []
    if not state.get("pyproject_present"):
        actions.append("fail_missing_pyproject")
        return actions
    venv_missing = not state.get("venv_python")
    if venv_missing:
        actions.append("create_venv")
    if venv_missing or not state.get("pyproject_matches"):
        actions.append("upgrade_pip")
        actions.append("install_dev_extras")
    if venv_missing or (not state.get("pre_commit_hook_exists")) or (not state.get("pre_commit_matches")):
        actions.append("install_pre_commit_hooks")
    return actions


def describe_plan(state: State) -> list[str]:
    if not state.get("pyproject_present"):
        return ["fail_missing_pyproject: would stop (pyproject.toml missing)"]

    lines = []
    if not state.get("venv_python"):
        lines.append("create_venv: would create .venv")
    elif state.get("venv_exists") or state.get("venv_python"):
        lines.append("create_venv: no-op (venv already exists)")

    venv_missing = not state.get("venv_python")
    if venv_missing or not state.get("pyproject_matches"):
        lines.append("upgrade_pip: would run .venv python -m pip install -U pip")
        lines.append('install_dev_extras: would run .venv python -m pip install -e ".[dev]"')
    else:
        lines.append("upgrade_pip: no-op (bootstrap state unchanged)")
        lines.append("install_dev_extras: no-op (bootstrap state unchanged)")

    if not venv_missing and state.get("pre_commit_matches") and state.get("pre_commit_hook_exists"):
        lines.append("install_pre_commit_hooks: no-op (hook already installed, state unchanged)")
    else:
        lines.append("install_pre_commit_hooks: would run .venv python -m pre_commit install --install-hooks")
    return lines


def _format_git_signing_status(signing_ok: bool, message: str) -> list[str]:
    status = "configured" if signing_ok else "not_configured"
    return [
        "  git_signing:",
        f"    status: {status}",
        f"    detail: {message}",
    ]


def _print_dry_run(
    state: State,
    plan: list[str],
    *,
    git_signing_status: tuple[bool, str],
) -> None:
    print("[DRY-RUN] Repo bootstrap plan")
    print(f"  repo_root: {state.get('repo_root')}")
    print(f"  platform: {state.get('platform')}")
    print(f"  system_python: {state.get('system_python')}")
    print(f"  venv_path: {state.get('venv_path')}")
    print(f"  venv_python: {state.get('venv_python')}")
    print("  actions:")
    for line in describe_plan(state):
        print(f"    - {line}")
    signing_ok, message = git_signing_status
    for line in _format_git_signing_status(signing_ok, message):
        print(line)


def _run_step(argv: list[str], *, cwd: Path) -> int:
    proc = subprocess.run(argv, cwd=str(cwd), check=False)
    return int(proc.returncode)


def _create_venv(
    *,
    repo_root: Path,
    venv_path: Path,
    system_python_cmd: list[str],
) -> int:
    argv = [*system_python_cmd, "-m", "venv", str(venv_path)]
    return _run_step(argv, cwd=repo_root)


def _ensure_venv(
    *,
    repo_root: Path,
    platform: str,
    plan: list[str],
    which: Callable[[str], str | None],
) -> tuple[Path | None, int]:
    venv_path = repo_root / VENV_DIR
    if "create_venv" in plan:
        system_python_cmd = resolve_system_python_cmd(platform, which=which)
        if not system_python_cmd:
            print("[FAIL] System Python not found on PATH.", file=sys.stderr)
            return None, EXIT_FAILED
        print(f"[INFO] Creating venv at {venv_path}.")
        create_rc = _create_venv(
            repo_root=repo_root,
            venv_path=venv_path,
            system_python_cmd=system_python_cmd,
        )
        if create_rc != 0:
            return None, create_rc

    venv_python = _resolve_venv_python(repo_root, platform)
    if venv_python is None:
        print("[FAIL] Repo venv python not found after creation.", file=sys.stderr)
        return None, EXIT_FAILED
    return venv_python, EXIT_OK


def _run_bootstrap_actions(*, repo_root: Path, venv_python: Path, plan: list[str]) -> int:
    if "upgrade_pip" in plan:
        print("[INFO] Upgrading pip.")
        pip_rc = _run_step(
            [str(venv_python), "-m", "pip", "install", "-U", "pip"],
            cwd=repo_root,
        )
        if pip_rc != 0:
            return pip_rc

    if "install_dev_extras" in plan:
        print("[INFO] Installing dev dependencies.")
        dev_rc = _run_step(
            [str(venv_python), "-m", "pip", "install", "-e", ".[dev]"],
            cwd=repo_root,
        )
        if dev_rc != 0:
            return dev_rc

    if "install_pre_commit_hooks" in plan:
        print("[INFO] Installing pre-commit hooks.")
        hook_rc = _run_step(
            [str(venv_python), "-m", "pre_commit", "install", "--install-hooks"],
            cwd=repo_root,
        )
        if hook_rc != 0:
            return hook_rc

    return EXIT_OK


def _report_git_signing(signing_status: tuple[bool, str]) -> None:
    signing_ok, message = signing_status
    if signing_ok:
        print("[OK] Git signing is configured.")
        return
    print(f"[WARN] Git signing is not configured: {message}")
    print("Run: python -m scripts.devops.setup_git_signing")


def _verify_packages(venv_python: Path, requirements: list[str]) -> list[str]:
    if not requirements:
        return []
    script = (
        "import json, sys\n"
        "from importlib import metadata\n"
        "reqs = json.loads(sys.argv[1])\n"
        "missing = []\n"
        "for name in reqs:\n"
        "    try:\n"
        "        metadata.distribution(name)\n"
        "    except metadata.PackageNotFoundError:\n"
        "        missing.append(name)\n"
        "if missing:\n"
        "    print('\\n'.join(missing))\n"
        "    sys.exit(1)\n"
    )
    proc = subprocess.run(
        [str(venv_python), "-c", script, json.dumps(requirements)],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        return []
    stdout = (proc.stdout or "").strip()
    if stdout:
        return stdout.splitlines()
    return requirements


def _verify_bootstrap(*, repo_root: Path, platform: str) -> int:
    venv_python = _resolve_venv_python(repo_root, platform)
    if venv_python is None:
        print("[FAIL] Repo venv python not found.", file=sys.stderr)
        return EXIT_FAILED
    requirements = _load_dev_requirements(repo_root)
    if not requirements:
        print("[OK] No dev requirements found to verify.")
        return EXIT_OK
    missing = _verify_packages(venv_python, requirements)
    if missing:
        print("[FAIL] Missing dev dependencies in repo venv:", file=sys.stderr)
        for name in missing:
            print(f"- {name}", file=sys.stderr)
        return EXIT_FAILED
    print("[OK] Bootstrap verify: dev dependencies present.")
    return EXIT_OK


def run_bootstrap(
    *,
    repo_root: Path,
    platform: str,
    dry_run: bool = False,
    verify: bool = False,
    which: Callable[[str], str | None] = shutil.which,
) -> int:
    if not (repo_root / PYPROJECT_FILE).exists():
        print("[FAIL] pyproject.toml not found; run from repo root.", file=sys.stderr)
        return EXIT_FAILED

    state = collect_state(repo_root=repo_root, platform=platform, which=which)
    plan = build_plan(state)
    signing_status = check_git_signing()
    if verify:
        return _verify_bootstrap(repo_root=repo_root, platform=platform)
    if dry_run:
        _print_dry_run(state, plan, git_signing_status=signing_status)
        return EXIT_OK

    if not plan:
        print("[OK] Repo bootstrap already up to date.")
        _report_git_signing(signing_status)
        return EXIT_OK

    venv_python, venv_rc = _ensure_venv(
        repo_root=repo_root,
        platform=platform,
        plan=plan,
        which=which,
    )
    if venv_rc != 0 or venv_python is None:
        return venv_rc

    actions_rc = _run_bootstrap_actions(repo_root=repo_root, venv_python=venv_python, plan=plan)
    if actions_rc != 0:
        return actions_rc

    desired_state = state.get("desired_state")
    state_path = state.get("state_path")
    if isinstance(desired_state, dict) and isinstance(state_path, str):
        write_bootstrap_state(Path(state_path), desired_state)
    _report_git_signing(signing_status)
    return EXIT_OK


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap the repo venv and dev tooling.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print current state and planned actions without making changes.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify dev dependencies are installed in the repo venv.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    if args.dry_run and args.verify:
        print("[FAIL] --dry-run and --verify cannot be used together.", file=sys.stderr)
        return EXIT_FAILED
    repo_root = repo_root_from_script(Path(__file__))
    return run_bootstrap(
        repo_root=repo_root,
        platform=sys.platform,
        dry_run=args.dry_run,
        verify=args.verify,
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))  # pragma: no cover
