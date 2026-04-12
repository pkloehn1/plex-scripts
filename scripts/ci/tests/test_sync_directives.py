"""Tests for scripts.ci.sync_directives."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ci.sync_directives import (
    SyncResult,
    format_summary,
    get_excludes,
    load_config,
    resolve_files,
    sync_files,
)


def _create_tree(root: Path, files: list[str]) -> None:
    """Create a directory tree with stub files."""
    for name in files:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"content of {name}\n", encoding="utf-8")


@pytest.fixture()
def sample_config() -> dict:
    return {
        "targets": [
            {"repo": "owner/repo-a"},
            {"repo": "owner/repo-b"},
        ],
        "files": [
            "CLAUDE.md",
            ".github/copilot-instructions.md",
            ".editorconfig",
            ".pre-commit-config.yaml",
            ".github/workflows/sync-directives-push.yml",
            ".github/workflows/sync-directives-pull.yml",
            "scripts/ci/sync_directives.py",
            "scripts/ci/tests/test_sync_directives.py",
        ],
        "directories": [
            {"path": ".github/ISSUE_TEMPLATE", "pattern": "*"},
            {"path": ".github/linters", "pattern": "*"},
            {"path": "docs/repository-standards", "pattern": "*.md"},
            {"path": "docs/repository-standards/style-guides", "pattern": "*.md"},
        ],
        "exclude": {
            "owner/repo-b": [
                ".github/ISSUE_TEMPLATE/incident-rca.yml",
                ".dclintrc",
            ],
        },
    }


# --- resolve_files -----------------------------------------------------------


class TestResolveFiles:
    def test_individual_files(self, tmp_path: Path, sample_config: dict) -> None:
        _create_tree(tmp_path, ["CLAUDE.md", ".github/copilot-instructions.md"])
        result = resolve_files(tmp_path, sample_config)
        assert "CLAUDE.md" in result
        assert ".github/copilot-instructions.md" in result

    def test_missing_files_skipped(self, tmp_path: Path, sample_config: dict) -> None:
        result = resolve_files(tmp_path, sample_config)
        assert result == []

    def test_directory_patterns(self, tmp_path: Path, sample_config: dict) -> None:
        _create_tree(
            tmp_path,
            [".github/ISSUE_TEMPLATE/work-package.yml", ".github/ISSUE_TEMPLATE/incident-rca.yml"],
        )
        result = resolve_files(tmp_path, sample_config)
        assert ".github/ISSUE_TEMPLATE/work-package.yml" in result
        assert ".github/ISSUE_TEMPLATE/incident-rca.yml" in result

    def test_non_matching_files_ignored(self, tmp_path: Path, sample_config: dict) -> None:
        _create_tree(tmp_path, [".github/other/notes.txt"])
        result = resolve_files(tmp_path, sample_config)
        assert result == []

    def test_infrastructure_files(self, tmp_path: Path, sample_config: dict) -> None:
        _create_tree(
            tmp_path,
            [
                ".github/workflows/sync-directives-push.yml",
                "scripts/ci/sync_directives.py",
            ],
        )
        result = resolve_files(tmp_path, sample_config)
        assert ".github/workflows/sync-directives-push.yml" in result
        assert "scripts/ci/sync_directives.py" in result

    def test_linter_configs(self, tmp_path: Path, sample_config: dict) -> None:
        _create_tree(
            tmp_path,
            [
                ".editorconfig",
                ".github/linters/.markdownlint.json",
                ".github/linters/.yaml-lint.yml",
            ],
        )
        result = resolve_files(tmp_path, sample_config)
        assert ".editorconfig" in result
        assert ".github/linters/.markdownlint.json" in result
        assert ".github/linters/.yaml-lint.yml" in result

    def test_style_guides(self, tmp_path: Path, sample_config: dict) -> None:
        _create_tree(
            tmp_path,
            [
                "docs/repository-standards/devsecops-workflow.md",
                "docs/repository-standards/style-guides/python-style-guide.md",
            ],
        )
        result = resolve_files(tmp_path, sample_config)
        assert "docs/repository-standards/devsecops-workflow.md" in result
        assert "docs/repository-standards/style-guides/python-style-guide.md" in result

    def test_glob_pattern_in_files_expands(self, tmp_path: Path) -> None:
        _create_tree(
            tmp_path,
            [
                "scripts/ci/alpha.py",
                "scripts/ci/beta.py",
                "scripts/ci/gamma.py",
            ],
        )
        config: dict = {"files": ["scripts/ci/*.py"], "directories": []}
        result = resolve_files(tmp_path, config)
        assert "scripts/ci/alpha.py" in result
        assert "scripts/ci/beta.py" in result
        assert "scripts/ci/gamma.py" in result

    def test_glob_pattern_no_match_returns_empty(self, tmp_path: Path) -> None:
        tmp_path.mkdir(exist_ok=True)
        config: dict = {"files": ["scripts/ci/*.py"], "directories": []}
        result = resolve_files(tmp_path, config)
        assert result == []

    def test_glob_skips_directories(self, tmp_path: Path) -> None:
        _create_tree(tmp_path, ["scripts/ci/real_file.py"])
        (tmp_path / "scripts" / "ci" / "sub_dir.py").mkdir(parents=True, exist_ok=True)
        config: dict = {"files": ["scripts/ci/*.py"], "directories": []}
        result = resolve_files(tmp_path, config)
        assert "scripts/ci/real_file.py" in result
        assert len(result) == 1

    def test_literal_and_glob_mixed(self, tmp_path: Path) -> None:
        _create_tree(
            tmp_path,
            [
                "CLAUDE.md",
                "scripts/ci/alpha.py",
                "scripts/ci/beta.py",
            ],
        )
        config: dict = {
            "files": ["CLAUDE.md", "scripts/ci/*.py"],
            "directories": [],
        }
        result = resolve_files(tmp_path, config)
        assert "CLAUDE.md" in result
        assert "scripts/ci/alpha.py" in result
        assert "scripts/ci/beta.py" in result

    def test_glob_deduplicates_with_directories(self, tmp_path: Path) -> None:
        _create_tree(
            tmp_path,
            [
                "scripts/ci/alpha.py",
                "scripts/ci/beta.py",
            ],
        )
        config: dict = {
            "files": ["scripts/ci/*.py"],
            "directories": [{"path": "scripts/ci", "pattern": "*.py"}],
        }
        result = resolve_files(tmp_path, config)
        assert result.count("scripts/ci/alpha.py") == 1
        assert result.count("scripts/ci/beta.py") == 1

    def test_recursive_glob_pattern(self, tmp_path: Path) -> None:
        _create_tree(
            tmp_path,
            [
                "scripts/__init__.py",
                "scripts/ci/__init__.py",
                "scripts/ci/tests/__init__.py",
            ],
        )
        config: dict = {"files": ["scripts/**/__init__.py"], "directories": []}
        result = resolve_files(tmp_path, config)
        assert "scripts/__init__.py" in result
        assert "scripts/ci/__init__.py" in result
        assert "scripts/ci/tests/__init__.py" in result

    def test_glob_with_nonexistent_source_dir(self, tmp_path: Path) -> None:
        config: dict = {"files": ["nonexistent/dir/*.py"], "directories": []}
        result = resolve_files(tmp_path, config)
        assert result == []

    def test_literal_path_still_requires_file_exists(self, tmp_path: Path) -> None:
        config: dict = {"files": ["missing.md"], "directories": []}
        result = resolve_files(tmp_path, config)
        assert result == []

    def test_sync_simulation_with_globs(self, tmp_path: Path) -> None:
        """Full sync cycle with globs, overlay, and per-target excludes."""
        src = tmp_path / "source"
        tgt = tmp_path / "target"
        src.mkdir()
        tgt.mkdir()
        _create_tree(
            src,
            [
                "CLAUDE.md",
                "scripts/ci/alpha.py",
                "scripts/ci/beta.py",
                "scripts/ci/gamma.py",
                "docs/standards/guide-a.md",
                "docs/standards/guide-b.md",
            ],
        )
        config: dict = {
            "files": ["CLAUDE.md", "scripts/ci/*.py"],
            "directories": [{"path": "docs/standards", "pattern": "*.md"}],
            "exclude": {
                "owner/spoke-a": ["scripts/ci/gamma.py"],
            },
        }
        result = sync_files(
            source=src,
            target=tgt,
            config=config,
            target_repo="owner/spoke-a",
        )
        assert "CLAUDE.md" in result.copied
        assert "scripts/ci/alpha.py" in result.copied
        assert "scripts/ci/beta.py" in result.copied
        assert "scripts/ci/gamma.py" in result.skipped
        assert "docs/standards/guide-a.md" in result.copied
        assert "docs/standards/guide-b.md" in result.copied
        assert (tgt / "scripts/ci/alpha.py").exists()
        assert not (tgt / "scripts/ci/gamma.py").exists()


# --- get_excludes -------------------------------------------------------------


class TestGetExcludes:
    def test_returns_excludes_for_target(self, sample_config: dict) -> None:
        assert get_excludes(sample_config, "owner/repo-b") == {
            ".github/ISSUE_TEMPLATE/incident-rca.yml",
            ".dclintrc",
        }

    def test_empty_for_unknown_target(self, sample_config: dict) -> None:
        assert get_excludes(sample_config, "owner/unknown") == set()

    def test_handles_missing_key(self) -> None:
        assert get_excludes({"files": []}, "owner/repo") == set()

    def test_handles_null_value(self) -> None:
        assert get_excludes({"exclude": None}, "owner/repo") == set()


# --- sync_files ---------------------------------------------------------------


class TestSyncFiles:
    def test_copies_files(self, tmp_path: Path, sample_config: dict) -> None:
        src = tmp_path / "source"
        tgt = tmp_path / "target"
        src.mkdir()
        tgt.mkdir()
        _create_tree(src, ["CLAUDE.md", ".github/copilot-instructions.md"])

        result = sync_files(
            source=src,
            target=tgt,
            config=sample_config,
            target_repo="owner/repo-a",
        )

        assert len(result.copied) == 2
        assert (tgt / "CLAUDE.md").exists()
        assert (tgt / ".github/copilot-instructions.md").exists()

    def test_exclusions_respected(self, tmp_path: Path, sample_config: dict) -> None:
        src = tmp_path / "source"
        tgt = tmp_path / "target"
        src.mkdir()
        tgt.mkdir()
        _create_tree(
            src,
            [
                "CLAUDE.md",
                ".github/ISSUE_TEMPLATE/work-package.yml",
                ".github/ISSUE_TEMPLATE/incident-rca.yml",
            ],
        )

        result = sync_files(
            source=src,
            target=tgt,
            config=sample_config,
            target_repo="owner/repo-b",
        )

        assert ".github/ISSUE_TEMPLATE/incident-rca.yml" in result.skipped
        assert ".github/ISSUE_TEMPLATE/work-package.yml" in result.copied
        assert not (tgt / ".github/ISSUE_TEMPLATE/incident-rca.yml").exists()
        assert (tgt / ".github/ISSUE_TEMPLATE/work-package.yml").exists()

    def test_creates_parent_directories(self, tmp_path: Path, sample_config: dict) -> None:
        src = tmp_path / "source"
        tgt = tmp_path / "target"
        src.mkdir()
        tgt.mkdir()
        _create_tree(src, [".github/copilot-instructions.md"])

        sync_files(
            source=src,
            target=tgt,
            config=sample_config,
            target_repo="owner/repo-a",
        )

        assert (tgt / ".github/copilot-instructions.md").exists()

    def test_preserves_file_content(self, tmp_path: Path, sample_config: dict) -> None:
        src = tmp_path / "source"
        tgt = tmp_path / "target"
        src.mkdir()
        tgt.mkdir()
        _create_tree(src, ["CLAUDE.md"])

        sync_files(
            source=src,
            target=tgt,
            config=sample_config,
            target_repo="owner/repo-a",
        )

        assert (tgt / "CLAUDE.md").read_text(encoding="utf-8") == "content of CLAUDE.md\n"

    def test_no_files_returns_empty(self, tmp_path: Path, sample_config: dict) -> None:
        src = tmp_path / "source"
        tgt = tmp_path / "target"
        src.mkdir()
        tgt.mkdir()

        result = sync_files(
            source=src,
            target=tgt,
            config=sample_config,
            target_repo="owner/repo-a",
        )

        assert result == SyncResult(copied=(), skipped=(), removed=(), unchanged=())

    def test_removes_stale_files(self, tmp_path: Path, sample_config: dict) -> None:
        src = tmp_path / "source"
        tgt = tmp_path / "target"
        src.mkdir()
        tgt.mkdir()
        _create_tree(src, ["CLAUDE.md"])
        _create_tree(
            tgt,
            ["CLAUDE.md", ".github/ISSUE_TEMPLATE/90-obsolete.yml"],
        )

        result = sync_files(
            source=src,
            target=tgt,
            config=sample_config,
            target_repo="owner/repo-a",
        )

        assert ".github/ISSUE_TEMPLATE/90-obsolete.yml" in result.removed
        assert not (tgt / ".github/ISSUE_TEMPLATE/90-obsolete.yml").exists()
        assert (tgt / "CLAUDE.md").exists()

    def test_removal_respects_exclusions(self, tmp_path: Path, sample_config: dict) -> None:
        src = tmp_path / "source"
        tgt = tmp_path / "target"
        src.mkdir()
        tgt.mkdir()
        _create_tree(tgt, [".github/ISSUE_TEMPLATE/incident-rca.yml"])

        result = sync_files(
            source=src,
            target=tgt,
            config=sample_config,
            target_repo="owner/repo-b",
        )

        assert ".github/ISSUE_TEMPLATE/incident-rca.yml" not in result.removed
        assert (tgt / ".github/ISSUE_TEMPLATE/incident-rca.yml").exists()

    def test_idempotent_rerun(self, tmp_path: Path, sample_config: dict) -> None:
        src = tmp_path / "source"
        tgt = tmp_path / "target"
        src.mkdir()
        tgt.mkdir()
        _create_tree(src, ["CLAUDE.md", ".github/copilot-instructions.md"])

        first = sync_files(
            source=src,
            target=tgt,
            config=sample_config,
            target_repo="owner/repo-a",
        )
        assert len(first.copied) == 2

        second = sync_files(
            source=src,
            target=tgt,
            config=sample_config,
            target_repo="owner/repo-a",
        )
        assert second.copied == ()
        assert len(second.unchanged) == 2
        assert second.removed == ()

    def test_skips_source_entry_that_becomes_non_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        src = tmp_path / "source"
        tgt = tmp_path / "target"
        src.mkdir()
        tgt.mkdir()
        # resolve_files returns a path that is not a real file on disk (TOCTOU).
        import scripts.ci.sync_directives as sync_mod

        monkeypatch.setattr(sync_mod, "resolve_files", lambda source, config: ["CLAUDE.md"])

        config = {"files": ["CLAUDE.md"], "directories": []}
        result = sync_files(
            source=src,
            target=tgt,
            config=config,
            target_repo="owner/repo-a",
        )

        assert result.copied == ()
        assert result.unchanged == ()

    def test_unchanged_when_content_matches(self, tmp_path: Path, sample_config: dict) -> None:
        src = tmp_path / "source"
        tgt = tmp_path / "target"
        src.mkdir()
        tgt.mkdir()
        _create_tree(src, ["CLAUDE.md"])
        _create_tree(tgt, ["CLAUDE.md"])

        result = sync_files(
            source=src,
            target=tgt,
            config=sample_config,
            target_repo="owner/repo-a",
        )

        assert "CLAUDE.md" in result.unchanged
        assert result.copied == ()

    def test_precommit_config_merged_with_overlay(
        self,
        tmp_path: Path,
    ) -> None:
        """Sync merges hub .pre-commit-config.yaml with spoke overlay."""
        import yaml

        fixtures = Path(__file__).parent / "fixtures" / "precommit_merge"
        src = tmp_path / "source"
        tgt = tmp_path / "target"
        src.mkdir()
        tgt.mkdir()

        # Place hub config in source
        hub_content = (fixtures / "hub-config.yaml").read_text(encoding="utf-8")
        hub_path = src / ".pre-commit-config.yaml"
        hub_path.parent.mkdir(parents=True, exist_ok=True)
        hub_path.write_text(hub_content, encoding="utf-8")

        # Place spoke overlay in target
        overlay_content = (fixtures / "overlay.yaml").read_text(encoding="utf-8")
        overlay_path = tgt / ".pre-commit-config.local.yaml"
        overlay_path.write_text(overlay_content, encoding="utf-8")

        config = {"files": [".pre-commit-config.yaml"], "directories": []}
        result = sync_files(
            source=src,
            target=tgt,
            config=config,
            target_repo="owner/repo-a",
        )

        assert ".pre-commit-config.yaml" in result.copied
        merged = yaml.safe_load(
            (tgt / ".pre-commit-config.yaml").read_text(encoding="utf-8"),
        )
        hook_ids = [hook["id"] for entry in merged["repos"] for hook in entry.get("hooks", [])]
        assert "hub-hook-a" in hook_ids
        assert "spoke-hook-x" in hook_ids

    def test_precommit_config_no_overlay_first_sync_copies(
        self,
        tmp_path: Path,
    ) -> None:
        """First sync without overlay copies hub config verbatim."""
        fixtures = Path(__file__).parent / "fixtures" / "precommit_merge"
        src = tmp_path / "source"
        tgt = tmp_path / "target"
        src.mkdir()
        tgt.mkdir()

        hub_content = (fixtures / "hub-config.yaml").read_text(encoding="utf-8")
        hub_path = src / ".pre-commit-config.yaml"
        hub_path.write_text(hub_content, encoding="utf-8")

        config = {"files": [".pre-commit-config.yaml"], "directories": []}
        result = sync_files(
            source=src,
            target=tgt,
            config=config,
            target_repo="owner/repo-a",
        )

        assert ".pre-commit-config.yaml" in result.copied
        target_content = (tgt / ".pre-commit-config.yaml").read_text(encoding="utf-8")
        assert target_content == hub_content

    def test_precommit_config_no_overlay_unchanged_on_rerun(
        self,
        tmp_path: Path,
    ) -> None:
        """Second sync without overlay reports unchanged."""
        fixtures = Path(__file__).parent / "fixtures" / "precommit_merge"
        src = tmp_path / "source"
        tgt = tmp_path / "target"
        src.mkdir()
        tgt.mkdir()

        hub_content = (fixtures / "hub-config.yaml").read_text(encoding="utf-8")
        (src / ".pre-commit-config.yaml").write_text(hub_content, encoding="utf-8")
        (tgt / ".pre-commit-config.yaml").write_text(hub_content, encoding="utf-8")

        config = {"files": [".pre-commit-config.yaml"], "directories": []}
        result = sync_files(
            source=src,
            target=tgt,
            config=config,
            target_repo="owner/repo-a",
        )

        assert ".pre-commit-config.yaml" in result.unchanged


# --- load_config --------------------------------------------------------------


class TestLoadConfig:
    def test_loads_yaml(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "config.yml"
        cfg_path.write_text(
            "targets:\n  - repo: owner/repo\nfiles:\n  - CLAUDE.md\n",
            encoding="utf-8",
        )
        config = load_config(cfg_path)
        assert config["targets"] == [{"repo": "owner/repo"}]
        assert config["files"] == ["CLAUDE.md"]

    def test_empty_file_returns_empty_dict(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "empty.yml"
        cfg_path.write_text("", encoding="utf-8")
        assert load_config(cfg_path) == {}

    def test_non_dict_raises_value_error(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "list.yml"
        cfg_path.write_text("- item1\n- item2\n", encoding="utf-8")
        with pytest.raises(ValueError, match="expected a mapping"):
            load_config(cfg_path)


# --- format_summary -----------------------------------------------------------


class TestFormatSummary:
    def test_includes_all_sections(self) -> None:
        result = SyncResult(
            copied=("CLAUDE.md",),
            skipped=(".dclintrc",),
            removed=(".github/ISSUE_TEMPLATE/90-obsolete.yml",),
            unchanged=(".editorconfig",),
        )
        summary = format_summary(result, "owner/repo-a")
        assert "## Sync → `owner/repo-a`" in summary
        assert "Copied (1)" in summary
        assert "`CLAUDE.md`" in summary
        assert "Removed (1)" in summary
        assert "`.github/ISSUE_TEMPLATE/90-obsolete.yml`" in summary
        assert "Skipped (excluded) (1)" in summary
        assert "Unchanged (1)" in summary

    def test_empty_result(self) -> None:
        result = SyncResult(copied=(), skipped=(), removed=(), unchanged=())
        summary = format_summary(result, "owner/repo-b")
        assert "Copied (0)" in summary
        assert "_None._" in summary
