from __future__ import annotations

from pathlib import Path

import scripts.testing.hooks.check_commit_grouping as mod


def _set_staged_paths(monkeypatch, paths: list[str]) -> None:
    monkeypatch.setattr(mod, "_get_staged_paths", lambda: ([Path(path_str) for path_str in paths], []))


def test_allows_when_no_staged_paths(monkeypatch) -> None:
    _set_staged_paths(monkeypatch, [])
    assert mod.main() == 0


def test_allows_non_tooling_only(monkeypatch) -> None:
    _set_staged_paths(monkeypatch, ["README.md"])
    assert mod.main() == 0


def test_blocks_pre_commit_config_with_other_files(monkeypatch, capsys) -> None:
    _set_staged_paths(monkeypatch, [".pre-commit-config.yaml", "README.md"])
    assert mod.main() == 1
    err = capsys.readouterr().err
    assert ".pre-commit-config.yaml must be committed alone first" in err
    assert "README.md" in err


def test_blocks_pre_commit_config_with_other_tooling(monkeypatch, capsys) -> None:
    _set_staged_paths(monkeypatch, [".pre-commit-config.yaml", "scripts/precommit/run_python"])
    assert mod.main() == 1
    err = capsys.readouterr().err
    assert ".pre-commit-config.yaml must be committed alone first" in err
    assert "scripts/precommit/run_python" in err


def test_allows_pre_commit_config_alone(monkeypatch) -> None:
    _set_staged_paths(monkeypatch, [".pre-commit-config.yaml"])
    assert mod.main() == 0


def test_blocks_mixed_tooling_and_other(monkeypatch, capsys) -> None:
    _set_staged_paths(monkeypatch, ["scripts/precommit/run_python", "docs/guide.md"])
    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "commit tooling files must be committed separately" in err
    assert "scripts/precommit/run_python" in err
    assert "docs/guide.md" in err


def test_allows_tooling_only_group(monkeypatch) -> None:
    _set_staged_paths(
        monkeypatch,
        ["scripts/precommit/run_python", "scripts/testing/hooks/check_repo_layout.py"],
    )
    assert mod.main() == 0


def test_fails_when_git_diff_errors(monkeypatch, capsys) -> None:
    monkeypatch.setattr(mod, "_get_staged_paths", lambda: ([], ["git diff --cached failed: boom"]))
    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "git diff --cached failed" in err


def test_format_path_list_empty() -> None:
    """_format_path_list returns empty string for empty paths."""
    assert mod._format_path_list("Title", []) == ""
