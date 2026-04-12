from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.precommit.run_in_repo_venv import (
    build_exec_argv,
    repo_root_from_script,
    resolve_venv_python,
    run_in_venv,
)


def test_repo_root_from_script_points_to_repo_root() -> None:
    # scripts/precommit/run_in_repo_venv.py -> scripts/ -> repo root
    script_path = Path(__file__).resolve().parents[1] / "run_in_repo_venv.py"
    repo_root = repo_root_from_script(script_path)

    assert (repo_root / "pyproject.toml").exists(), "repo root should contain pyproject.toml"
    assert (repo_root / "scripts").is_dir(), "repo root should contain scripts/"


def test_resolve_venv_python_prefers_posix_path(tmp_path: Path) -> None:
    repo_root = tmp_path
    posix_python = repo_root / ".venv" / "bin" / "python"
    windows_python = repo_root / ".venv" / "Scripts" / "python.exe"

    windows_python.parent.mkdir(parents=True)
    windows_python.write_text("")

    posix_python.parent.mkdir(parents=True)
    posix_python.write_text("")

    assert resolve_venv_python(repo_root) == posix_python


def test_resolve_venv_python_falls_back_to_windows_path(tmp_path: Path) -> None:
    repo_root = tmp_path
    windows_python = repo_root / ".venv" / "Scripts" / "python.exe"

    windows_python.parent.mkdir(parents=True)
    windows_python.write_text("")

    assert resolve_venv_python(repo_root) == windows_python


def test_resolve_venv_python_none_when_missing(tmp_path: Path) -> None:
    assert resolve_venv_python(tmp_path) is None


def test_build_exec_argv() -> None:
    venv_python = Path("/repo/.venv/bin/python")
    argv = build_exec_argv(venv_python, ["-m", "pytest", "-q"])
    assert argv == [str(venv_python), "-m", "pytest", "-q"]


def test_run_in_venv_windows_uses_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    venv_python = Path("C:/repo/.venv/Scripts/python.exe")
    seen: dict[str, list[str]] = {}

    def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 5, stdout="", stderr="")

    monkeypatch.setattr("scripts.precommit.run_in_repo_venv.subprocess.run", fake_run)

    exit_code = run_in_venv(venv_python, ["-m", "pytest"], platform="nt")
    assert exit_code == 5
    assert seen["argv"] == [str(venv_python), "-m", "pytest"]
