#!/usr/bin/env python3
"""Execute a Python command using the repo-local virtualenv interpreter.

Intent:
- Keep pre-commit hooks as `language: system` (no pre-commit-managed venvs).
- Ensure the actual lint/test scripts run under the repository venv for
    consistent dependency resolution and behavior.

This wrapper is designed to be invoked by system-level tools (like pre-commit)
and then re-exec into the venv interpreter:

    python scripts/precommit/run_in_repo_venv.py <python args...>

Examples:
    python scripts/precommit/run_in_repo_venv.py scripts/linting/validate_heading_numbers.py
    python scripts/precommit/run_in_repo_venv.py -m pytest -q scripts/ci/tests

Notes:
- Requires a repo-local venv at `.venv/`.
- Works on Linux/macOS and Windows by selecting the appropriate venv python path.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_MISSING_VENV = 3
EXIT_EXEC_FAILED = 1


def repo_root_from_script(script_path: Path) -> Path:
    # scripts/precommit/run_in_repo_venv.py -> scripts/ -> repo root
    return script_path.resolve().parents[2]


def resolve_venv_python(repo_root: Path) -> Path | None:
    candidates = [
        repo_root / ".venv" / "bin" / "python",
        repo_root / ".venv" / "Scripts" / "python.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def build_exec_argv(venv_python: Path, python_args: list[str]) -> list[str]:
    return [str(venv_python), *python_args]


def run_in_venv(
    venv_python: Path,
    python_args: list[str],
    *,
    platform: str | None = None,
) -> int:
    argv = build_exec_argv(venv_python, python_args)
    if (platform or os.name) == "nt":
        completed = subprocess.run(argv, check=False)
        return int(completed.returncode)

    os.execv(str(venv_python), argv)
    print("Error: failed to exec into repo virtualenv interpreter", file=sys.stderr)
    return EXIT_EXEC_FAILED


def _is_executable_path(path: Path) -> bool:
    if sys.platform.startswith("win"):
        return path.exists()
    return path.exists() and os.access(path, os.X_OK)


def _format_missing_venv_error(repo_root: Path) -> str:
    return (
        "Repo virtualenv not found. Expected one of:\n"
        f"- {repo_root / '.venv' / 'bin' / 'python'}\n"
        f"- {repo_root / '.venv' / 'Scripts' / 'python.exe'}\n\n"
        "Troubleshooting:\n"
        "- Bootstrap the repo venv:\n"
        "    python -m scripts.dev.bootstrap_venv\n"
        "    python3 -m scripts.dev.bootstrap_venv\n"
        "    py -3 -m scripts.dev.bootstrap_venv\n"
        "- Create the venv and install dev deps (example):\n"
        "    python -m venv .venv\n"
        "    .venv/bin/python -m pip install -U pip\n"
        "    .venv/bin/python -m pip install -e '.[dev]'\n"
        "- If `pre-commit` is not on PATH, run it via the venv:\n"
        "    .venv/bin/python -m pre_commit run --all-files\n"
    )


def main(argv: list[str]) -> int:
    python_args = argv[1:]
    if not python_args:
        print(
            "Usage: python scripts/precommit/run_in_repo_venv.py <python args...>",
            file=sys.stderr,
        )
        return EXIT_USAGE

    repo_root = repo_root_from_script(Path(__file__))
    venv_python = resolve_venv_python(repo_root)
    if venv_python is None or not _is_executable_path(venv_python):
        if venv_python is not None and not _is_executable_path(venv_python):
            print(
                f"Repo virtualenv python is not executable: {venv_python}",
                file=sys.stderr,
            )
        print(_format_missing_venv_error(repo_root), file=sys.stderr)
        return EXIT_MISSING_VENV

    return run_in_venv(venv_python, python_args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
