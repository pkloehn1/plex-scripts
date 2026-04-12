"""Tests for the Traefik swarm lint-decision gate."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from scripts.ci import should_run_lint_traefik_swarm as mod


def test_main_returns_zero_and_prints_true_when_matching_paths(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with patch.object(
        mod,
        "read_changed_files",
        return_value=["stacks/edge/docker-compose.yml", "README.md"],
    ):
        result = mod.main()

    assert result == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "true"
    assert "stacks/edge/docker-compose.yml" in captured.err


def test_main_returns_zero_and_prints_false_when_no_matching_paths(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with patch.object(
        mod,
        "read_changed_files",
        return_value=["README.md", "scripts/ci/foo.py"],
    ):
        result = mod.main()

    assert result == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "false"


def test_main_fail_open_on_os_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with patch.object(
        mod,
        "read_changed_files",
        side_effect=OSError("file not found"),
    ):
        result = mod.main()

    assert result == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "true"
    assert "fail-open" in captured.err
