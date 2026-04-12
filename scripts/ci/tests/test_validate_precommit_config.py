"""Tests for scripts.ci.validate_precommit_config."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ci.validate_precommit_config import validate_precommit_config


def _write(path: Path, content: str) -> Path:
    """Write *content* to *path*, creating parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class TestValidatePrecommitConfig:
    def test_valid_config_returns_zero(self, tmp_path: Path) -> None:
        config = tmp_path / ".pre-commit-config.yaml"
        _write(config, "repos:\n  - repo: local\n    hooks:\n      - id: test\n")

        assert validate_precommit_config(config) == 0

    def test_missing_repos_key_returns_one(self, tmp_path: Path) -> None:
        config = tmp_path / ".pre-commit-config.yaml"
        _write(config, "fail_fast: false\n")

        assert validate_precommit_config(config) == 1

    def test_non_dict_config_returns_one(self, tmp_path: Path) -> None:
        config = tmp_path / ".pre-commit-config.yaml"
        _write(config, "- item1\n- item2\n")

        assert validate_precommit_config(config) == 1

    def test_empty_config_returns_one(self, tmp_path: Path) -> None:
        config = tmp_path / ".pre-commit-config.yaml"
        _write(config, "")

        assert validate_precommit_config(config) == 1

    def test_nonexistent_file_returns_zero(self, tmp_path: Path) -> None:
        config = tmp_path / "does-not-exist.yaml"

        assert validate_precommit_config(config) == 0

    def test_reports_repo_count(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        config = tmp_path / ".pre-commit-config.yaml"
        _write(
            config,
            "repos:\n  - repo: local\n    hooks:\n      - id: a\n  - repo: local\n    hooks:\n      - id: b\n",
        )

        validate_precommit_config(config)

        captured = capsys.readouterr()
        assert "Validated: 2 repo entries" in captured.out
