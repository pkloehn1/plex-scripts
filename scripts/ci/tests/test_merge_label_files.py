"""Tests for merge_label_files module."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.ci.merge_label_files import main, merge_label_files


def _write_yaml(path: Path, data: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8") as yml:
        yaml.safe_dump(data, yml, default_flow_style=False, sort_keys=False)


def test_merge_hub_and_spoke(tmp_path: Path) -> None:
    """Both files present — merged output contains all labels."""
    hub = [{"name": "type/bug", "color": "1d76db", "description": "Bug"}]
    spoke = [{"name": "service/foo", "color": "c5def5", "description": "Foo"}]
    _write_yaml(tmp_path / "hub.yml", hub)
    _write_yaml(tmp_path / "spoke.yml", spoke)
    output = tmp_path / "merged.yml"

    count = merge_label_files(tmp_path / "hub.yml", tmp_path / "spoke.yml", output)

    assert count == 2
    raw = output.read_text(encoding="utf-8")
    assert raw.startswith("---\n"), "Output must start with YAML document marker"
    assert raw.rstrip().endswith("..."), "Output must end with YAML document marker"
    result = yaml.safe_load(raw)
    assert result == hub + spoke


def test_merge_spoke_missing(tmp_path: Path) -> None:
    """Spoke file absent — only hub labels in output."""
    hub = [{"name": "type/bug", "color": "1d76db", "description": "Bug"}]
    _write_yaml(tmp_path / "hub.yml", hub)
    output = tmp_path / "merged.yml"

    count = merge_label_files(
        tmp_path / "hub.yml",
        tmp_path / "spoke.yml",
        output,
    )

    assert count == 1
    with output.open(encoding="utf-8") as yml:
        result = yaml.safe_load(yml)
    assert result == hub


def test_merge_empty_files(tmp_path: Path) -> None:
    """Both files exist but are empty YAML — output is empty list."""
    (tmp_path / "hub.yml").write_text("---\n...\n", encoding="utf-8")
    (tmp_path / "spoke.yml").write_text("---\n...\n", encoding="utf-8")
    output = tmp_path / "merged.yml"

    count = merge_label_files(tmp_path / "hub.yml", tmp_path / "spoke.yml", output)

    assert count == 0
    with output.open(encoding="utf-8") as yml:
        result = yaml.safe_load(yml)
    assert result == []


def test_merge_rejects_duplicate_names(tmp_path: Path) -> None:
    """Duplicate label names across hub and spoke raise ValueError."""
    hub = [{"name": "type/bug", "color": "1d76db", "description": "Bug"}]
    spoke = [{"name": "type/bug", "color": "ff0000", "description": "Duplicate"}]
    _write_yaml(tmp_path / "hub.yml", hub)
    _write_yaml(tmp_path / "spoke.yml", spoke)
    output = tmp_path / "merged.yml"

    with pytest.raises(ValueError, match="Duplicate label names found"):
        merge_label_files(tmp_path / "hub.yml", tmp_path / "spoke.yml", output)


def test_main_uses_repo_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """main() runs without error and prints label count."""
    from scripts.ci import merge_label_files as mod

    monkeypatch.setattr(mod, "repo_root", lambda: tmp_path)
    github_dir = tmp_path / ".github"
    github_dir.mkdir()
    _write_yaml(github_dir / "labels-hub.yml", [{"name": "type/bug", "color": "1d76db", "description": "Bug"}])

    result = main()

    assert result == 0
    captured = capsys.readouterr()
    assert "Merged 1 labels" in captured.out
    assert (github_dir / "labels-merged.yml").exists()
