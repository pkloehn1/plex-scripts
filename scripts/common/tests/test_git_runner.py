from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.common.git_runner import GitResult, run_git


class TestGitResult:
    def test_fields_stored_correctly(self) -> None:
        result = GitResult(returncode=0, stdout="output", stderr="")
        assert result.returncode == 0
        assert result.stdout == "output"
        assert result.stderr == ""

    def test_tuple_unpacking(self) -> None:
        result = GitResult(returncode=1, stdout="out", stderr="err")
        code, out, err = result
        assert code == 1
        assert out == "out"
        assert err == "err"

    def test_frozen_dataclass_rejects_mutation(self) -> None:
        from dataclasses import FrozenInstanceError

        import pytest

        result = GitResult(returncode=0, stdout="", stderr="")
        with pytest.raises(FrozenInstanceError):
            result.returncode = 1  # type: ignore[misc]


class TestRunGit:
    def test_successful_command_returns_result(self) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "main\n"
        mock_proc.stderr = ""
        with patch("scripts.common.git_runner.subprocess.run", return_value=mock_proc) as mock_run:
            result = run_git(["rev-parse", "--abbrev-ref", "HEAD"])
        mock_run.assert_called_once()
        assert result.returncode == 0
        assert result.stdout == "main\n"
        assert result.stderr == ""

    def test_passes_cwd_as_string(self, tmp_path: Path) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        with patch("scripts.common.git_runner.subprocess.run", return_value=mock_proc) as mock_run:
            run_git(["status"], cwd=tmp_path)
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["cwd"] == str(tmp_path)

    def test_cwd_none_passes_none(self) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        with patch("scripts.common.git_runner.subprocess.run", return_value=mock_proc) as mock_run:
            run_git(["status"])
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["cwd"] is None

    def test_git_not_found_returns_127(self) -> None:
        with patch("scripts.common.git_runner.subprocess.run", side_effect=FileNotFoundError):
            result = run_git(["status"])
        assert result.returncode == 127
        assert result.stdout == ""
        assert "git not found" in result.stderr

    def test_nonzero_exit_code_returned(self) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 128
        mock_proc.stdout = ""
        mock_proc.stderr = "fatal: not a git repo"
        with patch("scripts.common.git_runner.subprocess.run", return_value=mock_proc):
            result = run_git(["status"])
        assert result.returncode == 128

    def test_command_includes_git_prefix(self) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        with patch("scripts.common.git_runner.subprocess.run", return_value=mock_proc) as mock_run:
            run_git(["log", "--oneline"])
        cmd = mock_run.call_args.args[0]
        assert cmd[0] == "git"
        assert cmd[1] == "log"
        assert cmd[2] == "--oneline"
