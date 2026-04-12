"""Tests for .github/dependabot.yml configuration."""

from __future__ import annotations

from pathlib import Path

import yaml

from scripts.common.paths import repo_root

_DEPENDABOT_PATH = repo_root() / ".github" / "dependabot.yml"


def _load_yaml(path: Path) -> dict:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_dependabot_config_has_required_top_level_keys() -> None:
    assert _DEPENDABOT_PATH.exists()

    cfg = _load_yaml(_DEPENDABOT_PATH)

    assert cfg.get("version") == 2
    assert isinstance(cfg.get("updates"), list)
    assert cfg["updates"], "updates must be non-empty"


def test_dependabot_config_updates_are_minimal_and_supported() -> None:
    cfg = _load_yaml(_DEPENDABOT_PATH)
    updates = cfg["updates"]

    assert updates, "updates must be non-empty"
    assert all(isinstance(update, dict) for update in updates)

    ecosystems = {update.get("package-ecosystem") for update in updates}
    assert "github-actions" in ecosystems
    assert "pip" in ecosystems

    allowed_keys = {
        "package-ecosystem",
        "directory",
        "directories",
        "patterns",
        "schedule",
        "open-pull-requests-limit",
        "target-branch",
        "multi-ecosystem-group",
        "multi-ecosystem-groups",
        "labels",
        "reviewers",
        "assignees",
        "ignore",
        "groups",
        "commit-message",
        "rebase-strategy",
        "insecure-external-code-execution",
    }

    for update in updates:
        assert isinstance(update.get("package-ecosystem"), str)

        directory = update.get("directory")
        directories = update.get("directories")
        assert isinstance(directory, str) ^ isinstance(directories, list), (
            "Exactly one of directory or directories must be set"
        )
        if isinstance(directories, list):
            assert directories, "directories must be non-empty when used"
            assert all(isinstance(dir_str, str) and dir_str for dir_str in directories)

        schedule = update.get("schedule")
        assert isinstance(schedule, dict)
        assert schedule.get("interval") in {"daily", "weekly", "monthly"}

        unexpected = set(update.keys()) - allowed_keys
        assert not unexpected, f"Unexpected keys in dependabot update: {sorted(unexpected)}"

    github_actions_updates = [update for update in updates if update.get("package-ecosystem") == "github-actions"]
    assert len(github_actions_updates) == 1
    gha_update = github_actions_updates[0]
    gha_dirs = gha_update.get("directories") or [gha_update.get("directory")]
    assert "/" in gha_dirs, "github-actions update must include root directory"
