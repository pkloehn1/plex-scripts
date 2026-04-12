"""Tests for scripts.ci.parse_sync_targets."""

from __future__ import annotations

from pathlib import Path

from scripts.ci.parse_sync_targets import main


class TestMain:
    def test_prints_targets_as_json(self, tmp_path: Path, capsys: object) -> None:
        cfg = tmp_path / "config.yml"
        cfg.write_text(
            "targets:\n  - repo: owner/repo-a\n  - repo: owner/repo-b\n",
            encoding="utf-8",
        )
        main(cfg)
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert '[{"repo": "owner/repo-a"}, {"repo": "owner/repo-b"}]' in captured.out

    def test_empty_targets_prints_empty_array(self, tmp_path: Path, capsys: object) -> None:
        cfg = tmp_path / "config.yml"
        cfg.write_text("files:\n  - CLAUDE.md\n", encoding="utf-8")
        main(cfg)
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert "[]" in captured.out

    def test_null_targets_prints_empty_array(self, tmp_path: Path, capsys: object) -> None:
        cfg = tmp_path / "config.yml"
        cfg.write_text("targets:\n", encoding="utf-8")
        main(cfg)
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert "[]" in captured.out
