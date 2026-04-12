"""Tests for check_sync_directives_completeness hook."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts.common.git_runner import GitResult
from scripts.testing.hooks.check_sync_directives_completeness import (
    check_completeness,
    compute_governed_prefixes,
    expand_hub_only,
    get_tracked_files,
    main,
)


class StubGitRunner:
    """Stub that filters predefined tracked files by prefix."""

    def __init__(self, tracked_files: list[str]) -> None:
        self._tracked = tracked_files

    def run_git(self, args: list[str], *, cwd: Path | None = None) -> GitResult:
        if args[0] != "ls-files":
            return GitResult(1, "", "unexpected command")
        prefix = args[1] if len(args) > 1 else ""
        matching = [file_path for file_path in self._tracked if file_path.startswith(prefix)]
        stdout = "\n".join(matching) + "\n" if matching else ""
        return GitResult(0, stdout, "")


class FailGitRunner:
    """Stub that always returns a non-zero exit code."""

    def run_git(self, args: list[str], *, cwd: Path | None = None) -> GitResult:
        return GitResult(1, "", "simulated git failure")


def _write_config(tmp_path: Path, config: dict[str, Any]) -> Path:
    """Write a sync-directives YAML config and return its path."""
    config_dir = tmp_path / ".github"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "sync-directives.yml"
    config_path.write_text(yaml.dump(config), encoding="utf-8")
    return config_path


def _create_files(tmp_path: Path, paths: list[str]) -> None:
    """Create empty files at the given relative paths."""
    for rel_path in paths:
        full = tmp_path / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.touch()


# --- compute_governed_prefixes ---


class TestComputeGovernedPrefixes:
    def test_extracts_dir_from_files_entries(self) -> None:
        config: dict[str, Any] = {
            "files": ["scripts/ci/sync.py", "scripts/github/cli.py"],
        }
        result = compute_governed_prefixes(config)
        assert "scripts/ci/" in result
        assert "scripts/github/" in result

    def test_extracts_dir_from_directories_entries(self) -> None:
        config: dict[str, Any] = {
            "directories": [{"path": "scripts/testing", "pattern": "*.py"}],
        }
        result = compute_governed_prefixes(config)
        assert "scripts/testing/" in result

    def test_skips_root_level_files(self) -> None:
        config: dict[str, Any] = {
            "files": ["CLAUDE.md", "Makefile", "scripts/ci/sync.py"],
        }
        result = compute_governed_prefixes(config)
        assert all("/" in prefix for prefix in result)
        assert len(result) == 1

    def test_collapses_nested_prefixes(self) -> None:
        config: dict[str, Any] = {
            "files": [
                "scripts/ci/sync.py",
                "scripts/ci/tests/test_sync.py",
            ],
            "directories": [
                {"path": "scripts/ci/tests/fixtures", "pattern": "*.yaml"},
            ],
        }
        result = compute_governed_prefixes(config)
        assert result == ["scripts/ci/"]

    def test_empty_config_returns_empty(self) -> None:
        assert compute_governed_prefixes({}) == []

    def test_governed_roots_adds_floor_prefixes(self) -> None:
        config: dict[str, Any] = {
            "files": ["scripts/ci/sync.py"],
        }
        result = compute_governed_prefixes(config, governed_roots=["scripts"])
        assert result == ["scripts/"]

    def test_governed_roots_merges_with_config_prefixes(self) -> None:
        config: dict[str, Any] = {
            "files": [".github/workflows/ci.yml"],
        }
        result = compute_governed_prefixes(config, governed_roots=["scripts", ".github"])
        assert ".github/" in result
        assert "scripts/" in result


# --- get_tracked_files ---


class TestGetTrackedFiles:
    def test_returns_files_matching_prefixes(self) -> None:
        runner = StubGitRunner(["scripts/ci/sync.py", "scripts/ci/tests/test_sync.py", "README.md"])
        tracked, errors = get_tracked_files(["scripts/ci/"], Path("."), runner)
        assert tracked == {"scripts/ci/sync.py", "scripts/ci/tests/test_sync.py"}
        assert errors == []

    def test_git_failure_returns_violation(self) -> None:
        tracked, errors = get_tracked_files(["scripts/"], Path("."), FailGitRunner())
        assert tracked == set()
        assert len(errors) == 1
        assert "git ls-files failed" in errors[0].reason
        assert errors[0].path == Path("scripts/")

    def test_normalizes_backslashes(self) -> None:
        runner = StubGitRunner(["scripts\\ci\\sync.py"])
        tracked, _errors = get_tracked_files(["scripts\\ci\\"], Path("."), runner)
        assert "scripts/ci/sync.py" in tracked

    def test_empty_prefixes_returns_empty(self) -> None:
        runner = StubGitRunner(["scripts/ci/sync.py"])
        tracked, errors = get_tracked_files([], Path("."), runner)
        assert tracked == set()
        assert errors == []


# --- expand_hub_only ---


class TestExpandHubOnly:
    def test_literal_path_kept_as_is(self, tmp_path: Path) -> None:
        result = expand_hub_only(["scripts/ci/hub_tool.py"], tmp_path)
        assert result == {"scripts/ci/hub_tool.py"}

    def test_glob_pattern_expands_to_matching_files(self, tmp_path: Path) -> None:
        _create_files(
            tmp_path,
            [
                ".github/workflows/pre-commit.yml",
                ".github/workflows/super-linter.yml",
                ".github/workflows/sync-directives-push.yml",
            ],
        )
        result = expand_hub_only([".github/workflows/*.yml"], tmp_path)
        assert ".github/workflows/pre-commit.yml" in result
        assert ".github/workflows/super-linter.yml" in result
        assert ".github/workflows/sync-directives-push.yml" in result

    def test_glob_ignores_directories(self, tmp_path: Path) -> None:
        subdir = tmp_path / ".github" / "workflows" / "subdir"
        subdir.mkdir(parents=True)
        _create_files(tmp_path, [".github/workflows/ci.yml"])
        result = expand_hub_only([".github/workflows/*"], tmp_path)
        assert result == {".github/workflows/ci.yml"}

    def test_empty_list_returns_empty(self, tmp_path: Path) -> None:
        assert expand_hub_only([], tmp_path) == set()

    def test_glob_no_matches_returns_empty(self, tmp_path: Path) -> None:
        result = expand_hub_only([".github/prompts/*.md"], tmp_path)
        assert result == set()

    def test_mixed_literal_and_glob(self, tmp_path: Path) -> None:
        _create_files(tmp_path, [".github/workflows/ci.yml"])
        result = expand_hub_only(["scripts/ci/hub.py", ".github/workflows/*.yml"], tmp_path)
        assert "scripts/ci/hub.py" in result
        assert ".github/workflows/ci.yml" in result

    def test_literal_with_dot_prefix_normalized(self, tmp_path: Path) -> None:
        result = expand_hub_only(["./scripts/ci/hub.py"], tmp_path)
        assert result == {"scripts/ci/hub.py"}

    def test_literal_with_backslash_normalized(self, tmp_path: Path) -> None:
        result = expand_hub_only(["scripts\\ci\\hub.py"], tmp_path)
        assert result == {"scripts/ci/hub.py"}


# --- check_completeness ---


class TestCheckCompleteness:
    def test_all_covered_no_violations(self, tmp_path: Path) -> None:
        files = ["scripts/ci/sync.py", "scripts/ci/utils.py"]
        _create_files(tmp_path, files)
        config: dict[str, Any] = {"files": files}
        runner = StubGitRunner(files)

        violations = check_completeness(config, tmp_path, runner)
        assert violations == []

    def test_uncovered_file_produces_violation(self, tmp_path: Path) -> None:
        covered = ["scripts/ci/sync.py"]
        tracked = ["scripts/ci/sync.py", "scripts/ci/new_file.py"]
        _create_files(tmp_path, covered)
        config: dict[str, Any] = {"files": covered}
        runner = StubGitRunner(tracked)

        violations = check_completeness(config, tmp_path, runner)
        assert len(violations) == 1
        assert violations[0].path == Path("scripts/ci/new_file.py")
        assert "not listed" in violations[0].reason

    def test_hub_only_excludes_file(self, tmp_path: Path) -> None:
        covered = ["scripts/ci/sync.py"]
        tracked = ["scripts/ci/sync.py", "scripts/ci/hub_tool.py"]
        _create_files(tmp_path, covered)
        config: dict[str, Any] = {
            "files": covered,
            "hub_only": ["scripts/ci/hub_tool.py"],
        }
        runner = StubGitRunner(tracked)

        violations = check_completeness(config, tmp_path, runner)
        assert violations == []

    def test_hub_only_glob_excludes_matching_files(self, tmp_path: Path) -> None:
        covered = ["scripts/ci/sync.py"]
        hub_files = ["scripts/ci/hub_a.py", "scripts/ci/hub_b.py"]
        tracked = [*covered, *hub_files]
        _create_files(tmp_path, [*covered, *hub_files])
        config: dict[str, Any] = {
            "files": covered,
            "hub_only": ["scripts/ci/hub_*.py"],
        }
        runner = StubGitRunner(tracked)

        violations = check_completeness(config, tmp_path, runner)
        assert violations == []

    def test_directory_pattern_covers_file(self, tmp_path: Path) -> None:
        _create_files(tmp_path, ["scripts/linting/check.py"])
        config: dict[str, Any] = {
            "directories": [{"path": "scripts/linting", "pattern": "*.py"}],
        }
        runner = StubGitRunner(["scripts/linting/check.py"])

        violations = check_completeness(config, tmp_path, runner)
        assert violations == []

    def test_ungoverned_directory_ignored(self, tmp_path: Path) -> None:
        _create_files(tmp_path, ["scripts/ci/sync.py"])
        config: dict[str, Any] = {"files": ["scripts/ci/sync.py"]}
        runner = StubGitRunner(["scripts/ci/sync.py", "docs/notes.md"])

        violations = check_completeness(config, tmp_path, runner)
        assert violations == []

    def test_empty_config_returns_no_violations(self, tmp_path: Path) -> None:
        runner = StubGitRunner(["scripts/ci/sync.py"])
        violations = check_completeness({}, tmp_path, runner)
        assert violations == []

    def test_hub_only_missing_key_treated_as_empty(self, tmp_path: Path) -> None:
        tracked = ["scripts/ci/sync.py", "scripts/ci/extra.py"]
        _create_files(tmp_path, ["scripts/ci/sync.py"])
        config: dict[str, Any] = {"files": ["scripts/ci/sync.py"]}
        runner = StubGitRunner(tracked)

        violations = check_completeness(config, tmp_path, runner)
        assert len(violations) == 1
        assert violations[0].path == Path("scripts/ci/extra.py")

    def test_hub_only_none_treated_as_empty(self, tmp_path: Path) -> None:
        tracked = ["scripts/ci/sync.py", "scripts/ci/extra.py"]
        _create_files(tmp_path, ["scripts/ci/sync.py"])
        config: dict[str, Any] = {
            "files": ["scripts/ci/sync.py"],
            "hub_only": None,
        }
        runner = StubGitRunner(tracked)

        violations = check_completeness(config, tmp_path, runner)
        assert len(violations) == 1

    def test_git_failure_returns_error_violations(self, tmp_path: Path) -> None:
        _create_files(tmp_path, ["scripts/ci/sync.py"])
        config: dict[str, Any] = {"files": ["scripts/ci/sync.py"]}

        violations = check_completeness(config, tmp_path, FailGitRunner())
        assert len(violations) == 1
        assert "git ls-files failed" in violations[0].reason

    def test_governed_roots_catches_new_directory(self, tmp_path: Path) -> None:
        _create_files(tmp_path, ["scripts/ci/sync.py"])
        config: dict[str, Any] = {
            "files": ["scripts/ci/sync.py"],
            "governed_roots": ["scripts"],
        }
        # scripts/newpkg/tool.py is tracked but not in any config entry
        runner = StubGitRunner(["scripts/ci/sync.py", "scripts/newpkg/tool.py"])

        violations = check_completeness(config, tmp_path, runner)
        assert len(violations) == 1
        assert violations[0].path == Path("scripts/newpkg/tool.py")


# --- main ---


class TestMain:
    def test_returns_zero_when_all_covered(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        files = ["scripts/ci/sync.py"]
        _create_files(tmp_path, files)
        _write_config(tmp_path, {"files": files})

        monkeypatch.setattr(
            "scripts.testing.hooks.check_sync_directives_completeness.repo_root",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "scripts.testing.hooks.check_sync_directives_completeness.run_git",
            StubGitRunner(files).run_git,
        )

        assert main() == 0

    def test_returns_one_with_stderr_on_violations(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        covered = ["scripts/ci/sync.py"]
        tracked = ["scripts/ci/sync.py", "scripts/ci/missing.py"]
        _create_files(tmp_path, covered)
        _write_config(tmp_path, {"files": covered})

        monkeypatch.setattr(
            "scripts.testing.hooks.check_sync_directives_completeness.repo_root",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "scripts.testing.hooks.check_sync_directives_completeness.run_git",
            StubGitRunner(tracked).run_git,
        )

        assert main() == 1
        captured = capsys.readouterr()
        assert "scripts/ci/missing.py" in captured.err
        assert "sync-directives completeness check failed" in captured.err

    def test_returns_zero_when_config_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "scripts.testing.hooks.check_sync_directives_completeness.repo_root",
            lambda: tmp_path,
        )
        assert main() == 0

    def test_violation_message_includes_fix_guidance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        covered = ["scripts/ci/sync.py"]
        tracked = ["scripts/ci/sync.py", "scripts/ci/new.py"]
        _create_files(tmp_path, covered)
        _write_config(tmp_path, {"files": covered})

        monkeypatch.setattr(
            "scripts.testing.hooks.check_sync_directives_completeness.repo_root",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "scripts.testing.hooks.check_sync_directives_completeness.run_git",
            StubGitRunner(tracked).run_git,
        )

        main()
        captured = capsys.readouterr()
        assert "files:" in captured.err
        assert "directories:" in captured.err
        assert "hub_only:" in captured.err

    def test_git_failure_surfaces_in_main(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _create_files(tmp_path, ["scripts/ci/sync.py"])
        _write_config(tmp_path, {"files": ["scripts/ci/sync.py"]})

        monkeypatch.setattr(
            "scripts.testing.hooks.check_sync_directives_completeness.repo_root",
            lambda: tmp_path,
        )
        monkeypatch.setattr(
            "scripts.testing.hooks.check_sync_directives_completeness.run_git",
            FailGitRunner().run_git,
        )

        assert main() == 1
        captured = capsys.readouterr()
        assert "git ls-files failed" in captured.err
