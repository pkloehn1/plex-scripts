from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.precommit.run_if_exists import (
    GuardResult,
    _is_absolute,
    check_guard,
    main,
    run_command,
)

# -- check_guard --------------------------------------------------------------


def test_check_guard_path_exists(tmp_path: Path) -> None:
    target = tmp_path / "some_script.py"
    target.touch()
    with patch("scripts.precommit.run_if_exists.repo_root", return_value=tmp_path):
        result = check_guard("some_script.py")
    assert result == GuardResult(skipped=False, message="", exit_code=0)


def test_check_guard_path_missing(tmp_path: Path) -> None:
    with patch("scripts.precommit.run_if_exists.repo_root", return_value=tmp_path):
        result = check_guard("nonexistent/path")
    assert result.skipped is True
    assert "does not exist" in result.message
    assert result.exit_code == 0


def test_check_guard_rejects_posix_absolute_path() -> None:
    result = check_guard("/usr/local/bin/some_script.py")
    assert result.exit_code == 2
    assert "must be relative" in result.message
    assert "repo-relative path" in result.message


def test_check_guard_rejects_windows_absolute_path() -> None:
    result = check_guard("C:\\Users\\foo\\script.py")
    assert result.exit_code == 2
    assert "must be relative" in result.message


def test_is_absolute_posix() -> None:
    assert _is_absolute("/usr/local/bin/foo") is True


def test_is_absolute_windows() -> None:
    assert _is_absolute("C:\\Users\\foo") is True


def test_is_absolute_relative() -> None:
    assert _is_absolute("scripts/precommit/foo.py") is False


def test_check_guard_rejects_path_traversal(tmp_path: Path) -> None:
    with patch("scripts.precommit.run_if_exists.repo_root", return_value=tmp_path):
        result = check_guard("../outside")
    assert result.exit_code == 2
    assert "escapes the repository root" in result.message


def test_check_guard_rejects_embedded_traversal(tmp_path: Path) -> None:
    with patch("scripts.precommit.run_if_exists.repo_root", return_value=tmp_path):
        result = check_guard("scripts/../../outside")
    assert result.exit_code == 2
    assert "escapes the repository root" in result.message


def test_main_rejects_path_traversal(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with patch("scripts.precommit.run_if_exists.repo_root", return_value=tmp_path):
        exit_code = main(["run_if_exists.py", "../escape", "echo", "hi"])
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "escapes the repository root" in captured.err


def test_check_guard_directory_exists(tmp_path: Path) -> None:
    target_dir = tmp_path / "scripts" / "cloudflare" / "tests"
    target_dir.mkdir(parents=True)
    with patch("scripts.precommit.run_if_exists.repo_root", return_value=tmp_path):
        result = check_guard("scripts/cloudflare/tests")
    assert result.skipped is False


# -- run_command ---------------------------------------------------------------


def test_run_command_success() -> None:
    with patch("scripts.precommit.run_if_exists.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        assert run_command(["echo", "hello"]) == 0
        mock_run.assert_called_once_with(["echo", "hello"], check=False)


def test_run_command_failure() -> None:
    with patch("scripts.precommit.run_if_exists.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        assert run_command(["false"]) == 1


def test_run_command_prepends_python_for_py_files() -> None:
    with patch("scripts.precommit.run_if_exists.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        assert run_command(["scripts/precommit/pytest_affected.py", "arg1"]) == 0
        mock_run.assert_called_once_with(
            [sys.executable, "scripts/precommit/pytest_affected.py", "arg1"],
            check=False,
        )


# -- main ---------------------------------------------------------------------


def test_main_no_args() -> None:
    assert main(["run_if_exists.py"]) == 2


def test_main_only_guard_path() -> None:
    assert main(["run_if_exists.py", "some/path"]) == 2


def test_main_rejects_absolute_guard_path(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["run_if_exists.py", "/usr/local/bin/script.py", "echo", "hi"])
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "must be relative" in captured.err


def test_main_guard_missing_skips(tmp_path: Path) -> None:
    with patch("scripts.precommit.run_if_exists.repo_root", return_value=tmp_path):
        exit_code = main(["run_if_exists.py", "missing/script.py", "echo", "hi"])
    assert exit_code == 0


def test_main_guard_exists_delegates(tmp_path: Path) -> None:
    target = tmp_path / "existing.py"
    target.touch()
    with (
        patch("scripts.precommit.run_if_exists.repo_root", return_value=tmp_path),
        patch("scripts.precommit.run_if_exists.run_command", return_value=0) as mock_cmd,
    ):
        exit_code = main(["run_if_exists.py", "existing.py", "python", "-c", "pass"])
    assert exit_code == 0
    mock_cmd.assert_called_once_with(["python", "-c", "pass"])


def test_main_guard_exists_propagates_failure(tmp_path: Path) -> None:
    target = tmp_path / "existing.py"
    target.touch()
    with (
        patch("scripts.precommit.run_if_exists.repo_root", return_value=tmp_path),
        patch("scripts.precommit.run_if_exists.run_command", return_value=1),
    ):
        exit_code = main(["run_if_exists.py", "existing.py", "python", "-c", "fail"])
    assert exit_code == 1
