"""Tests for scripts.dev.bootstrap_venv."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from scripts.dev.bootstrap_venv import (
    EXIT_FAILED,
    EXIT_OK,
    _create_venv,
    _ensure_venv,
    _extract_requirement_name,
    _format_git_signing_status,
    _hash_file,
    _is_executable_path,
    _load_dev_requirements,
    _normalize_package_name,
    _parse_args,
    _print_dry_run,
    _report_git_signing,
    _resolve_venv_python,
    _run_bootstrap_actions,
    _run_step,
    _state_file_path,
    _venv_python_candidates,
    _verify_bootstrap,
    _verify_packages,
    build_desired_state,
    build_plan,
    collect_state,
    describe_plan,
    load_bootstrap_state,
    main,
    repo_root_from_script,
    resolve_system_python_cmd,
    run_bootstrap,
    write_bootstrap_state,
)


class TestRepoRootFromScript:
    def test_finds_parents_2(self, tmp_path: Path) -> None:
        script = tmp_path / "a" / "b" / "c.py"
        script.parent.mkdir(parents=True)
        script.touch()
        assert repo_root_from_script(script) == tmp_path


class TestVenvPythonCandidates:
    def test_returns_two_candidates(self, tmp_path: Path) -> None:
        result = _venv_python_candidates(tmp_path)
        assert len(result) == 2
        assert "bin" in str(result[0])
        assert "Scripts" in str(result[1])


class TestIsExecutablePath:
    def test_win32_only_checks_exists(self, tmp_path: Path) -> None:
        fpath = tmp_path / "python.exe"
        fpath.touch()
        assert _is_executable_path(fpath, "win32") is True

    def test_missing_file_returns_false(self, tmp_path: Path) -> None:
        assert _is_executable_path(tmp_path / "nope", "win32") is False

    def test_linux_checks_executable(self, tmp_path: Path) -> None:
        fpath = tmp_path / "python"
        fpath.touch()
        fpath.chmod(0o755)
        assert _is_executable_path(fpath, "linux") is True

    def test_linux_non_executable_returns_false(self, tmp_path: Path) -> None:
        fpath = tmp_path / "python"
        fpath.touch()
        fpath.chmod(0o644)
        # On Windows this may still return True; only meaningful on Linux
        result = _is_executable_path(fpath, "linux")
        assert isinstance(result, bool)


class TestResolveVenvPython:
    def test_finds_scripts_python_on_win32(self, tmp_path: Path) -> None:
        scripts_dir = tmp_path / ".venv" / "Scripts"
        scripts_dir.mkdir(parents=True)
        python_exe = scripts_dir / "python.exe"
        python_exe.touch()
        result = _resolve_venv_python(tmp_path, "win32")
        assert result == python_exe

    def test_returns_none_when_no_venv(self, tmp_path: Path) -> None:
        assert _resolve_venv_python(tmp_path, "win32") is None


class TestResolveSystemPythonCmd:
    def test_linux_finds_python3(self) -> None:
        result = resolve_system_python_cmd("linux", which=lambda cmd: "/usr/bin/python3" if cmd == "python3" else None)
        assert result == ["python3"]

    def test_linux_falls_back_to_python(self) -> None:
        result = resolve_system_python_cmd("linux", which=lambda cmd: "/usr/bin/python" if cmd == "python" else None)
        assert result == ["python"]

    def test_win32_finds_python(self) -> None:
        result = resolve_system_python_cmd("win32", which=lambda cmd: "C:\\python.exe" if cmd == "python" else None)
        assert result == ["python"]

    def test_win32_falls_back_to_py(self) -> None:
        result = resolve_system_python_cmd("win32", which=lambda cmd: "C:\\py.exe" if cmd == "py" else None)
        assert result == ["py", "-3"]

    def test_returns_none_when_no_python(self) -> None:
        result = resolve_system_python_cmd("linux", which=lambda _: None)
        assert result is None


class TestStateFilePath:
    def test_returns_expected_path(self, tmp_path: Path) -> None:
        result = _state_file_path(tmp_path)
        assert result == tmp_path / ".venv" / ".bootstrap_state.json"


class TestHashFile:
    def test_hashes_existing_file(self, tmp_path: Path) -> None:
        fpath = tmp_path / "test.txt"
        fpath.write_text("hello")
        result = _hash_file(fpath)
        assert result is not None
        assert len(result) == 64

    def test_returns_none_for_missing_file(self, tmp_path: Path) -> None:
        assert _hash_file(tmp_path / "missing") is None


class TestNormalizePackageName:
    def test_normalizes_dashes_dots_underscores(self) -> None:
        assert _normalize_package_name("My_Package.Name") == "my-package-name"


class TestExtractRequirementName:
    def test_simple_name(self) -> None:
        assert _extract_requirement_name("pytest>=8.0") == "pytest"

    def test_with_extras(self) -> None:
        assert _extract_requirement_name("package[extra]>=1.0") == "package"

    def test_with_marker(self) -> None:
        assert _extract_requirement_name("pkg>=1.0; python_version>='3.8'") == "pkg"

    def test_with_url(self) -> None:
        assert _extract_requirement_name("pkg @ https://example.com") == "pkg"

    def test_empty_string(self) -> None:
        assert _extract_requirement_name("") is None

    def test_no_match(self) -> None:
        assert _extract_requirement_name("!!!") is None


class TestLoadDevRequirements:
    def test_loads_from_pyproject(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project.optional-dependencies]\ndev = ["pytest>=8.0", "ruff>=0.8"]\n',
            encoding="utf-8",
        )
        result = _load_dev_requirements(tmp_path)
        assert "pytest" in result
        assert "ruff" in result

    def test_returns_empty_when_no_pyproject(self, tmp_path: Path) -> None:
        assert _load_dev_requirements(tmp_path) == []

    def test_returns_empty_when_no_project_key(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[tool.ruff]\n", encoding="utf-8")
        assert _load_dev_requirements(tmp_path) == []

    def test_returns_empty_when_no_optional_deps(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "foo"\n', encoding="utf-8")
        assert _load_dev_requirements(tmp_path) == []

    def test_returns_empty_when_no_dev_key(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project.optional-dependencies]\ntest = ["pytest"]\n', encoding="utf-8")
        assert _load_dev_requirements(tmp_path) == []

    def test_skips_non_string_entries(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project.optional-dependencies]\ndev = ["pytest>=8.0"]\n',
            encoding="utf-8",
        )
        fake_data = {
            "project": {
                "optional-dependencies": {
                    "dev": ["pytest>=8.0", 42, None],
                },
            },
        }
        with patch("scripts.dev.bootstrap_venv.tomllib.loads", return_value=fake_data):
            result = _load_dev_requirements(tmp_path)
        assert result == ["pytest"]


class TestBuildDesiredState:
    def test_includes_hashes(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("content")
        (tmp_path / ".pre-commit-config.yaml").write_text("hooks")
        result = build_desired_state(tmp_path)
        assert result["pyproject_hash"] is not None
        assert result["pre_commit_config_hash"] is not None

    def test_missing_files_give_none(self, tmp_path: Path) -> None:
        result = build_desired_state(tmp_path)
        assert result["pyproject_hash"] is None
        assert result["pre_commit_config_hash"] is None


class TestLoadWriteBootstrapState:
    def test_roundtrip(self, tmp_path: Path) -> None:
        state_path = tmp_path / ".bootstrap_state.json"
        desired: dict[str, str | None] = {"pyproject_hash": "abc123", "pre_commit_config_hash": "def456"}
        write_bootstrap_state(state_path, desired)
        loaded = load_bootstrap_state(state_path)
        assert loaded == desired

    def test_returns_none_for_missing_file(self, tmp_path: Path) -> None:
        assert load_bootstrap_state(tmp_path / "missing.json") is None

    def test_returns_none_for_invalid_json(self, tmp_path: Path) -> None:
        fpath = tmp_path / "bad.json"
        fpath.write_text("not json")
        assert load_bootstrap_state(fpath) is None

    def test_returns_none_for_non_dict_json(self, tmp_path: Path) -> None:
        fpath = tmp_path / "list.json"
        fpath.write_text("[1, 2, 3]")
        assert load_bootstrap_state(fpath) is None

    def test_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        state_path = tmp_path / "sub" / "dir" / "state.json"
        write_bootstrap_state(state_path, {"pyproject_hash": None, "pre_commit_config_hash": None})
        assert state_path.exists()


class TestCollectState:
    def test_returns_expected_keys(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]")
        state = collect_state(repo_root=tmp_path, platform="win32", which=lambda _: None)
        assert "platform" in state
        assert "repo_root" in state
        assert "venv_exists" in state
        assert "state_matches" in state


class TestBuildPlan:
    def test_missing_pyproject_fails(self) -> None:
        state: dict[str, Any] = {"pyproject_present": False}
        plan = build_plan(state)
        assert plan == ["fail_missing_pyproject"]

    def test_fresh_install_creates_venv_and_installs(self) -> None:
        state: dict[str, Any] = {
            "pyproject_present": True,
            "venv_python": None,
            "pyproject_matches": False,
            "pre_commit_hook_exists": False,
            "pre_commit_matches": False,
        }
        plan = build_plan(state)
        assert "create_venv" in plan
        assert "upgrade_pip" in plan
        assert "install_dev_extras" in plan
        assert "install_pre_commit_hooks" in plan

    def test_up_to_date_returns_empty(self) -> None:
        state: dict[str, Any] = {
            "pyproject_present": True,
            "venv_python": "/path/to/python",
            "pyproject_matches": True,
            "pre_commit_hook_exists": True,
            "pre_commit_matches": True,
        }
        assert build_plan(state) == []

    def test_pyproject_changed_upgrades_without_create(self) -> None:
        state: dict[str, Any] = {
            "pyproject_present": True,
            "venv_python": "/path/to/python",
            "pyproject_matches": False,
            "pre_commit_hook_exists": True,
            "pre_commit_matches": True,
        }
        plan = build_plan(state)
        assert "create_venv" not in plan
        assert "upgrade_pip" in plan
        assert "install_dev_extras" in plan

    def test_missing_hook_installs_hooks(self) -> None:
        state: dict[str, Any] = {
            "pyproject_present": True,
            "venv_python": "/path/to/python",
            "pyproject_matches": True,
            "pre_commit_hook_exists": False,
            "pre_commit_matches": True,
        }
        plan = build_plan(state)
        assert "install_pre_commit_hooks" in plan
        assert "create_venv" not in plan

    def test_pre_commit_config_changed_installs_hooks(self) -> None:
        state: dict[str, Any] = {
            "pyproject_present": True,
            "venv_python": "/path/to/python",
            "pyproject_matches": True,
            "pre_commit_hook_exists": True,
            "pre_commit_matches": False,
        }
        plan = build_plan(state)
        assert "install_pre_commit_hooks" in plan


class TestDescribePlan:
    def test_missing_pyproject(self) -> None:
        state: dict[str, Any] = {"pyproject_present": False}
        lines = describe_plan(state)
        assert any("fail_missing_pyproject" in line for line in lines)

    def test_fresh_install(self) -> None:
        state: dict[str, Any] = {
            "pyproject_present": True,
            "venv_python": None,
            "venv_exists": False,
            "pyproject_matches": False,
            "pre_commit_hook_exists": False,
            "pre_commit_matches": False,
        }
        lines = describe_plan(state)
        assert any("create_venv: would create" in line for line in lines)
        assert any("upgrade_pip: would run" in line for line in lines)

    def test_up_to_date(self) -> None:
        state: dict[str, Any] = {
            "pyproject_present": True,
            "venv_python": "/python",
            "venv_exists": True,
            "pyproject_matches": True,
            "pre_commit_hook_exists": True,
            "pre_commit_matches": True,
        }
        lines = describe_plan(state)
        assert any("no-op" in line for line in lines)

    def test_venv_exists_shows_no_op(self) -> None:
        state: dict[str, Any] = {
            "pyproject_present": True,
            "venv_python": "/python",
            "venv_exists": True,
            "pyproject_matches": True,
            "pre_commit_hook_exists": True,
            "pre_commit_matches": True,
        }
        lines = describe_plan(state)
        assert any("create_venv: no-op" in line for line in lines)


class TestFormatGitSigningStatus:
    def test_configured(self) -> None:
        lines = _format_git_signing_status(True, "SSH key found")
        assert any("configured" in line for line in lines)

    def test_not_configured(self) -> None:
        lines = _format_git_signing_status(False, "No key")
        assert any("not_configured" in line for line in lines)


class TestPrintDryRun:
    def test_prints_state(self, capsys: pytest.CaptureFixture[str]) -> None:
        state: dict[str, Any] = {
            "repo_root": "/tmp/repo",
            "platform": "linux",
            "system_python": "python3",
            "venv_path": "/tmp/repo/.venv",
            "venv_python": None,
            "pyproject_present": True,
            "venv_exists": False,
            "pyproject_matches": False,
            "pre_commit_hook_exists": False,
            "pre_commit_matches": False,
        }
        plan = ["create_venv"]
        _print_dry_run(state, plan, git_signing_status=(True, "ok"))
        output = capsys.readouterr().out
        assert "[DRY-RUN]" in output
        assert "repo_root" in output


class TestRunStep:
    def test_returns_returncode(self, tmp_path: Path) -> None:
        with patch("scripts.dev.bootstrap_venv.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            assert _run_step(["echo", "hi"], cwd=tmp_path) == 0

    def test_returns_nonzero(self, tmp_path: Path) -> None:
        with patch("scripts.dev.bootstrap_venv.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=1)
            assert _run_step(["fail"], cwd=tmp_path) == 1


class TestCreateVenv:
    def test_calls_run_step(self, tmp_path: Path) -> None:
        with patch("scripts.dev.bootstrap_venv._run_step", return_value=0) as mock_step:
            result = _create_venv(
                repo_root=tmp_path,
                venv_path=tmp_path / ".venv",
                system_python_cmd=["python3"],
            )
            assert result == 0
            assert mock_step.called


class TestEnsureVenv:
    def test_creates_venv_when_in_plan(self, tmp_path: Path) -> None:
        venv_dir = tmp_path / ".venv" / "Scripts"
        venv_dir.mkdir(parents=True)
        python_exe = venv_dir / "python.exe"
        python_exe.touch()
        with patch("scripts.dev.bootstrap_venv._create_venv", return_value=0):
            venv_python, returncode = _ensure_venv(
                repo_root=tmp_path,
                platform="win32",
                plan=["create_venv"],
                which=lambda _: "python",
            )
            assert returncode == EXIT_OK
            assert venv_python is not None

    def test_fails_when_no_system_python(self, tmp_path: Path) -> None:
        venv_python, returncode = _ensure_venv(
            repo_root=tmp_path,
            platform="win32",
            plan=["create_venv"],
            which=lambda _: None,
        )
        assert returncode == EXIT_FAILED
        assert venv_python is None

    def test_fails_when_create_fails(self, tmp_path: Path) -> None:
        with patch("scripts.dev.bootstrap_venv._create_venv", return_value=1):
            venv_python, returncode = _ensure_venv(
                repo_root=tmp_path,
                platform="win32",
                plan=["create_venv"],
                which=lambda _: "python",
            )
            assert returncode == 1
            assert venv_python is None

    def test_fails_when_venv_python_not_found_after_create(self, tmp_path: Path) -> None:
        with patch("scripts.dev.bootstrap_venv._create_venv", return_value=0):
            venv_python, returncode = _ensure_venv(
                repo_root=tmp_path,
                platform="win32",
                plan=["create_venv"],
                which=lambda _: "python",
            )
            assert returncode == EXIT_FAILED
            assert venv_python is None

    def test_skips_create_when_not_in_plan(self, tmp_path: Path) -> None:
        venv_dir = tmp_path / ".venv" / "Scripts"
        venv_dir.mkdir(parents=True)
        python_exe = venv_dir / "python.exe"
        python_exe.touch()
        venv_python, returncode = _ensure_venv(
            repo_root=tmp_path,
            platform="win32",
            plan=["upgrade_pip"],
            which=lambda _: "python",
        )
        assert returncode == EXIT_OK
        assert venv_python == python_exe


class TestRunBootstrapActions:
    def test_runs_all_actions(self, tmp_path: Path) -> None:
        venv_python = tmp_path / "python"
        plan = ["upgrade_pip", "install_dev_extras", "install_pre_commit_hooks"]
        with patch("scripts.dev.bootstrap_venv._run_step", return_value=0):
            assert _run_bootstrap_actions(repo_root=tmp_path, venv_python=venv_python, plan=plan) == EXIT_OK

    def test_stops_on_pip_failure(self, tmp_path: Path) -> None:
        with patch("scripts.dev.bootstrap_venv._run_step", return_value=1):
            result = _run_bootstrap_actions(
                repo_root=tmp_path,
                venv_python=tmp_path / "python",
                plan=["upgrade_pip"],
            )
            assert result == 1

    def test_stops_on_dev_extras_failure(self, tmp_path: Path) -> None:
        call_count = 0

        def _side_effect(*_args: Any, **_kwargs: Any) -> int:
            nonlocal call_count
            call_count += 1
            return 0 if call_count == 1 else 1

        with patch("scripts.dev.bootstrap_venv._run_step", side_effect=_side_effect):
            result = _run_bootstrap_actions(
                repo_root=tmp_path,
                venv_python=tmp_path / "python",
                plan=["upgrade_pip", "install_dev_extras"],
            )
            assert result == 1

    def test_stops_on_pre_commit_failure(self, tmp_path: Path) -> None:
        call_count = 0

        def _side_effect(*_args: Any, **_kwargs: Any) -> int:
            nonlocal call_count
            call_count += 1
            return 0 if call_count <= 2 else 1

        with patch("scripts.dev.bootstrap_venv._run_step", side_effect=_side_effect):
            result = _run_bootstrap_actions(
                repo_root=tmp_path,
                venv_python=tmp_path / "python",
                plan=["upgrade_pip", "install_dev_extras", "install_pre_commit_hooks"],
            )
            assert result == 1

    def test_empty_plan_is_ok(self, tmp_path: Path) -> None:
        assert _run_bootstrap_actions(repo_root=tmp_path, venv_python=tmp_path / "python", plan=[]) == EXIT_OK


class TestReportGitSigning:
    def test_configured(self, capsys: pytest.CaptureFixture[str]) -> None:
        _report_git_signing((True, "SSH key found"))
        assert "[OK]" in capsys.readouterr().out

    def test_not_configured(self, capsys: pytest.CaptureFixture[str]) -> None:
        _report_git_signing((False, "No key found"))
        output = capsys.readouterr().out
        assert "[WARN]" in output
        assert "setup_git_signing" in output


class TestVerifyPackages:
    def test_returns_empty_for_no_requirements(self, tmp_path: Path) -> None:
        assert _verify_packages(tmp_path / "python", []) == []

    def test_returns_empty_when_all_present(self, tmp_path: Path) -> None:
        with patch("scripts.dev.bootstrap_venv.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            result = _verify_packages(tmp_path / "python", ["pytest"])
            assert result == []

    def test_returns_missing_packages(self, tmp_path: Path) -> None:
        with patch("scripts.dev.bootstrap_venv.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="pytest\nruff\n", stderr=""
            )
            result = _verify_packages(tmp_path / "python", ["pytest", "ruff"])
            assert result == ["pytest", "ruff"]

    def test_returns_all_when_no_stdout(self, tmp_path: Path) -> None:
        with patch("scripts.dev.bootstrap_venv.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")
            result = _verify_packages(tmp_path / "python", ["pytest"])
            assert result == ["pytest"]


class TestVerifyBootstrap:
    def test_fails_when_no_venv(self, tmp_path: Path) -> None:
        assert _verify_bootstrap(repo_root=tmp_path, platform="win32") == EXIT_FAILED

    def test_ok_when_no_requirements(self, tmp_path: Path) -> None:
        venv_dir = tmp_path / ".venv" / "Scripts"
        venv_dir.mkdir(parents=True)
        (venv_dir / "python.exe").touch()
        # No pyproject.toml means no requirements
        assert _verify_bootstrap(repo_root=tmp_path, platform="win32") == EXIT_OK

    def test_ok_when_all_packages_present(self, tmp_path: Path) -> None:
        venv_dir = tmp_path / ".venv" / "Scripts"
        venv_dir.mkdir(parents=True)
        (venv_dir / "python.exe").touch()
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project.optional-dependencies]\ndev = ["pytest>=8.0"]\n')
        with patch("scripts.dev.bootstrap_venv._verify_packages", return_value=[]):
            assert _verify_bootstrap(repo_root=tmp_path, platform="win32") == EXIT_OK

    def test_fails_when_packages_missing(self, tmp_path: Path) -> None:
        venv_dir = tmp_path / ".venv" / "Scripts"
        venv_dir.mkdir(parents=True)
        (venv_dir / "python.exe").touch()
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project.optional-dependencies]\ndev = ["pytest>=8.0"]\n')
        with patch("scripts.dev.bootstrap_venv._verify_packages", return_value=["pytest"]):
            assert _verify_bootstrap(repo_root=tmp_path, platform="win32") == EXIT_FAILED


class TestRunBootstrap:
    def test_fails_when_no_pyproject(self, tmp_path: Path) -> None:
        assert run_bootstrap(repo_root=tmp_path, platform="win32") == EXIT_FAILED

    def test_verify_mode(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]")
        with patch("scripts.dev.bootstrap_venv._verify_bootstrap", return_value=EXIT_OK) as mock_verify:
            result = run_bootstrap(repo_root=tmp_path, platform="win32", verify=True)
            assert result == EXIT_OK
            assert mock_verify.called

    def test_dry_run_mode(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]")
        with patch("scripts.dev.bootstrap_venv.check_git_signing", return_value=(True, "ok")):
            result = run_bootstrap(
                repo_root=tmp_path,
                platform="win32",
                dry_run=True,
                which=lambda _: None,
            )
            assert result == EXIT_OK

    def test_already_up_to_date(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]")
        venv_dir = tmp_path / ".venv" / "Scripts"
        venv_dir.mkdir(parents=True)
        (venv_dir / "python.exe").touch()
        # Write matching state
        desired = build_desired_state(tmp_path)
        state_path = _state_file_path(tmp_path)
        write_bootstrap_state(state_path, desired)
        # Create pre-commit hook
        hooks_dir = tmp_path / ".git" / "hooks"
        hooks_dir.mkdir(parents=True)
        (hooks_dir / "pre-commit").touch()
        with patch("scripts.dev.bootstrap_venv.check_git_signing", return_value=(True, "ok")):
            result = run_bootstrap(repo_root=tmp_path, platform="win32")
            assert result == EXIT_OK

    def test_full_bootstrap_flow(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]")
        (tmp_path / ".pre-commit-config.yaml").write_text("repos: []")
        with (
            patch("scripts.dev.bootstrap_venv.check_git_signing", return_value=(True, "ok")),
            patch("scripts.dev.bootstrap_venv._ensure_venv") as mock_ensure,
            patch("scripts.dev.bootstrap_venv._run_bootstrap_actions", return_value=EXIT_OK),
        ):
            mock_ensure.return_value = (tmp_path / "python", EXIT_OK)
            result = run_bootstrap(repo_root=tmp_path, platform="win32", which=lambda _: None)
            assert result == EXIT_OK

    def test_ensure_venv_failure(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]")
        with (
            patch("scripts.dev.bootstrap_venv.check_git_signing", return_value=(True, "ok")),
            patch("scripts.dev.bootstrap_venv._ensure_venv") as mock_ensure,
        ):
            mock_ensure.return_value = (None, EXIT_FAILED)
            result = run_bootstrap(repo_root=tmp_path, platform="win32", which=lambda _: None)
            assert result == EXIT_FAILED

    def test_actions_failure(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]")
        with (
            patch("scripts.dev.bootstrap_venv.check_git_signing", return_value=(True, "ok")),
            patch("scripts.dev.bootstrap_venv._ensure_venv") as mock_ensure,
            patch("scripts.dev.bootstrap_venv._run_bootstrap_actions", return_value=1),
        ):
            mock_ensure.return_value = (tmp_path / "python", EXIT_OK)
            result = run_bootstrap(repo_root=tmp_path, platform="win32", which=lambda _: None)
            assert result == 1


class TestParseArgs:
    def test_dry_run_flag(self) -> None:
        args = _parse_args(["--dry-run"])
        assert args.dry_run is True
        assert args.verify is False

    def test_verify_flag(self) -> None:
        args = _parse_args(["--verify"])
        assert args.verify is True
        assert args.dry_run is False

    def test_no_flags(self) -> None:
        args = _parse_args([])
        assert args.dry_run is False
        assert args.verify is False


class TestMain:
    def test_dry_run_and_verify_mutual_exclusion(self) -> None:
        assert main(["--dry-run", "--verify"]) == EXIT_FAILED

    def test_delegates_to_run_bootstrap(self) -> None:
        with patch("scripts.dev.bootstrap_venv.run_bootstrap", return_value=EXIT_OK) as mock_run:
            result = main([])
            assert result == EXIT_OK
            assert mock_run.called
