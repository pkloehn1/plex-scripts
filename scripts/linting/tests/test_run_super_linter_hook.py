"""Tests for scripts.run_super_linter_hook."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from scripts.run_super_linter_hook import main


class TestMain:
    def test_runs_bash(self) -> None:
        with patch("scripts.run_super_linter_hook.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            with pytest.raises(SystemExit, match="0"):
                main()
            cmd = mock_run.call_args[0][0]
            assert cmd[0] == "bash"
            assert cmd[1].endswith("local_super_linter.sh")

    def test_propagates_nonzero_exit_code(self) -> None:
        with patch("scripts.run_super_linter_hook.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=42)
            with pytest.raises(SystemExit, match="42"):
                main()

    def test_handles_exception(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch(
            "scripts.run_super_linter_hook.subprocess.run",
            side_effect=FileNotFoundError("bash not found"),
        ):
            with pytest.raises(SystemExit, match="1"):
                main()
            assert "bash not found" in capsys.readouterr().out
