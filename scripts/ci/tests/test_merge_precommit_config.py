"""Tests for scripts.ci.merge_precommit_config."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.ci.merge_precommit_config import (
    GENERATED_HEADER,
    LOCAL_OVERLAY,
    MergeResult,
    merge_precommit_config,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "precommit_merge"


def _write(path: Path, content: str) -> Path:
    """Write *content* to *path*, creating parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture()
def hub_config_yaml() -> str:
    """Minimal hub config with YAML anchor."""
    return (_FIXTURES / "hub-config.yaml").read_text(encoding="utf-8")


@pytest.fixture()
def overlay_yaml() -> str:
    """Minimal spoke-local overlay."""
    return (_FIXTURES / "overlay.yaml").read_text(encoding="utf-8")


# --- No overlay (passthrough) ------------------------------------------------


class TestNoOverlay:
    def test_copies_hub_as_is(
        self,
        tmp_path: Path,
        hub_config_yaml: str,
    ) -> None:
        hub_file = _write(tmp_path / "source" / ".pre-commit-config.yaml", hub_config_yaml)
        output = tmp_path / "target" / ".pre-commit-config.yaml"
        output.parent.mkdir(parents=True, exist_ok=True)

        result = merge_precommit_config(
            hub_config=hub_file,
            target_dir=tmp_path / "target",
            output=output,
        )

        assert result == MergeResult.PASSTHROUGH
        assert output.read_text(encoding="utf-8") == hub_file.read_text(encoding="utf-8")

    def test_returns_passthrough(
        self,
        tmp_path: Path,
        hub_config_yaml: str,
    ) -> None:
        hub_file = _write(tmp_path / "source" / ".pre-commit-config.yaml", hub_config_yaml)
        output = tmp_path / "target" / ".pre-commit-config.yaml"
        output.parent.mkdir(parents=True, exist_ok=True)

        result = merge_precommit_config(
            hub_config=hub_file,
            target_dir=tmp_path / "target",
            output=output,
        )

        assert result is MergeResult.PASSTHROUGH


# --- With overlay (merge) ----------------------------------------------------


class TestWithOverlay:
    def test_repos_merged_in_order(
        self,
        tmp_path: Path,
        hub_config_yaml: str,
        overlay_yaml: str,
    ) -> None:
        hub_file = _write(tmp_path / "source" / ".pre-commit-config.yaml", hub_config_yaml)
        target_dir = tmp_path / "target"
        _write(target_dir / LOCAL_OVERLAY, overlay_yaml)
        output = target_dir / ".pre-commit-config.yaml"

        merge_precommit_config(
            hub_config=hub_file,
            target_dir=target_dir,
            output=output,
        )

        merged = yaml.safe_load(output.read_text(encoding="utf-8"))
        repo_entries = merged["repos"]
        assert len(repo_entries) == 3
        # Hub repos first, overlay repos last
        hook_ids = [hook["id"] for entry in repo_entries for hook in entry.get("hooks", [])]
        assert hook_ids == ["hub-hook-a", "hub-hook-b", "spoke-hook-x"]

    def test_hub_top_level_keys_preserved(
        self,
        tmp_path: Path,
        hub_config_yaml: str,
        overlay_yaml: str,
    ) -> None:
        hub_file = _write(tmp_path / "source" / ".pre-commit-config.yaml", hub_config_yaml)
        target_dir = tmp_path / "target"
        _write(target_dir / LOCAL_OVERLAY, overlay_yaml)
        output = target_dir / ".pre-commit-config.yaml"

        merge_precommit_config(
            hub_config=hub_file,
            target_dir=target_dir,
            output=output,
        )

        merged = yaml.safe_load(output.read_text(encoding="utf-8"))
        assert merged["default_stages"] == ["pre-commit"]
        assert merged["fail_fast"] is False

    def test_returns_merged(
        self,
        tmp_path: Path,
        hub_config_yaml: str,
        overlay_yaml: str,
    ) -> None:
        hub_file = _write(tmp_path / "source" / ".pre-commit-config.yaml", hub_config_yaml)
        target_dir = tmp_path / "target"
        _write(target_dir / LOCAL_OVERLAY, overlay_yaml)
        output = target_dir / ".pre-commit-config.yaml"

        result = merge_precommit_config(
            hub_config=hub_file,
            target_dir=target_dir,
            output=output,
        )

        assert result is MergeResult.MERGED

    def test_generated_header_present(
        self,
        tmp_path: Path,
        hub_config_yaml: str,
        overlay_yaml: str,
    ) -> None:
        hub_file = _write(tmp_path / "source" / ".pre-commit-config.yaml", hub_config_yaml)
        target_dir = tmp_path / "target"
        _write(target_dir / LOCAL_OVERLAY, overlay_yaml)
        output = target_dir / ".pre-commit-config.yaml"

        merge_precommit_config(
            hub_config=hub_file,
            target_dir=target_dir,
            output=output,
        )

        content = output.read_text(encoding="utf-8")
        assert content.startswith(GENERATED_HEADER)

    def test_output_is_valid_yaml(
        self,
        tmp_path: Path,
        hub_config_yaml: str,
        overlay_yaml: str,
    ) -> None:
        hub_file = _write(tmp_path / "source" / ".pre-commit-config.yaml", hub_config_yaml)
        target_dir = tmp_path / "target"
        _write(target_dir / LOCAL_OVERLAY, overlay_yaml)
        output = target_dir / ".pre-commit-config.yaml"

        merge_precommit_config(
            hub_config=hub_file,
            target_dir=target_dir,
            output=output,
        )

        parsed = yaml.safe_load(output.read_text(encoding="utf-8"))
        assert isinstance(parsed, dict)
        assert "repos" in parsed

    def test_yaml_anchors_expanded(
        self,
        tmp_path: Path,
        hub_config_yaml: str,
        overlay_yaml: str,
    ) -> None:
        hub_file = _write(tmp_path / "source" / ".pre-commit-config.yaml", hub_config_yaml)
        target_dir = tmp_path / "target"
        _write(target_dir / LOCAL_OVERLAY, overlay_yaml)
        output = target_dir / ".pre-commit-config.yaml"

        merge_precommit_config(
            hub_config=hub_file,
            target_dir=target_dir,
            output=output,
        )

        merged = yaml.safe_load(output.read_text(encoding="utf-8"))
        hub_hook = merged["repos"][0]["hooks"][0]
        assert hub_hook["entry"] == "scripts/precommit/run_python"
        assert hub_hook["language"] == "system"


# --- Edge cases ---------------------------------------------------------------


class TestEdgeCases:
    def test_overlay_with_empty_repos(
        self,
        tmp_path: Path,
        hub_config_yaml: str,
    ) -> None:
        hub_file = _write(tmp_path / "source" / ".pre-commit-config.yaml", hub_config_yaml)
        target_dir = tmp_path / "target"
        _write(target_dir / LOCAL_OVERLAY, "---\nrepos: []\n")
        output = target_dir / ".pre-commit-config.yaml"

        result = merge_precommit_config(
            hub_config=hub_file,
            target_dir=target_dir,
            output=output,
        )

        merged = yaml.safe_load(output.read_text(encoding="utf-8"))
        assert len(merged["repos"]) == 2
        assert result is MergeResult.MERGED

    def test_empty_overlay_file_treated_as_no_overlay(
        self,
        tmp_path: Path,
        hub_config_yaml: str,
    ) -> None:
        hub_file = _write(tmp_path / "source" / ".pre-commit-config.yaml", hub_config_yaml)
        target_dir = tmp_path / "target"
        _write(target_dir / LOCAL_OVERLAY, "")
        output = target_dir / ".pre-commit-config.yaml"

        result = merge_precommit_config(
            hub_config=hub_file,
            target_dir=target_dir,
            output=output,
        )

        assert result is MergeResult.PASSTHROUGH

    def test_overlay_without_repos_key_treated_as_no_overlay(
        self,
        tmp_path: Path,
        hub_config_yaml: str,
    ) -> None:
        hub_file = _write(tmp_path / "source" / ".pre-commit-config.yaml", hub_config_yaml)
        target_dir = tmp_path / "target"
        _write(target_dir / LOCAL_OVERLAY, "---\nci:\n  skip: []\n")
        output = target_dir / ".pre-commit-config.yaml"

        result = merge_precommit_config(
            hub_config=hub_file,
            target_dir=target_dir,
            output=output,
        )

        assert result is MergeResult.PASSTHROUGH

    def test_creates_output_parent_directories(
        self,
        tmp_path: Path,
        hub_config_yaml: str,
        overlay_yaml: str,
    ) -> None:
        hub_file = _write(tmp_path / "source" / ".pre-commit-config.yaml", hub_config_yaml)
        target_dir = tmp_path / "target"
        _write(target_dir / LOCAL_OVERLAY, overlay_yaml)
        output = target_dir / "nested" / "dir" / ".pre-commit-config.yaml"

        merge_precommit_config(
            hub_config=hub_file,
            target_dir=target_dir,
            output=output,
        )

        assert output.is_file()

    def test_no_x_anchor_key_in_merged_output(
        self,
        tmp_path: Path,
        hub_config_yaml: str,
        overlay_yaml: str,
    ) -> None:
        """The x-python-wrapper anchor key should not appear in merged output."""
        hub_file = _write(tmp_path / "source" / ".pre-commit-config.yaml", hub_config_yaml)
        target_dir = tmp_path / "target"
        _write(target_dir / LOCAL_OVERLAY, overlay_yaml)
        output = target_dir / ".pre-commit-config.yaml"

        merge_precommit_config(
            hub_config=hub_file,
            target_dir=target_dir,
            output=output,
        )

        merged = yaml.safe_load(output.read_text(encoding="utf-8"))
        assert "x-python-wrapper" not in merged

    def test_overlay_repos_null_raises_value_error(
        self,
        tmp_path: Path,
        hub_config_yaml: str,
    ) -> None:
        hub_file = _write(tmp_path / "source" / ".pre-commit-config.yaml", hub_config_yaml)
        target_dir = tmp_path / "target"
        _write(target_dir / LOCAL_OVERLAY, "---\nrepos: null\n")
        output = target_dir / ".pre-commit-config.yaml"

        with pytest.raises(ValueError, match="overlay repos must be a list"):
            merge_precommit_config(
                hub_config=hub_file,
                target_dir=target_dir,
                output=output,
            )

    def test_overlay_repos_non_list_raises_value_error(
        self,
        tmp_path: Path,
        hub_config_yaml: str,
    ) -> None:
        hub_file = _write(tmp_path / "source" / ".pre-commit-config.yaml", hub_config_yaml)
        target_dir = tmp_path / "target"
        _write(target_dir / LOCAL_OVERLAY, "---\nrepos: not-a-list\n")
        output = target_dir / ".pre-commit-config.yaml"

        with pytest.raises(ValueError, match="overlay repos must be a list"):
            merge_precommit_config(
                hub_config=hub_file,
                target_dir=target_dir,
                output=output,
            )

    def test_hub_config_non_dict_raises_value_error(
        self,
        tmp_path: Path,
        overlay_yaml: str,
    ) -> None:
        hub_file = _write(tmp_path / "source" / ".pre-commit-config.yaml", "- item\n")
        target_dir = tmp_path / "target"
        _write(target_dir / LOCAL_OVERLAY, overlay_yaml)
        output = target_dir / ".pre-commit-config.yaml"

        with pytest.raises(ValueError, match="hub config must be a mapping"):
            merge_precommit_config(
                hub_config=hub_file,
                target_dir=target_dir,
                output=output,
            )

    def test_hub_repos_non_list_raises_value_error(
        self,
        tmp_path: Path,
        overlay_yaml: str,
    ) -> None:
        hub_file = _write(
            tmp_path / "source" / ".pre-commit-config.yaml",
            "repos: not-a-list\n",
        )
        target_dir = tmp_path / "target"
        _write(target_dir / LOCAL_OVERLAY, overlay_yaml)
        output = target_dir / ".pre-commit-config.yaml"

        with pytest.raises(ValueError, match="hub repos must be a list"):
            merge_precommit_config(
                hub_config=hub_file,
                target_dir=target_dir,
                output=output,
            )


# --- YAML output formatting ---------------------------------------------------


class TestYamlOutputFormatting:
    def test_merged_output_has_document_start_marker(
        self,
        tmp_path: Path,
        hub_config_yaml: str,
        overlay_yaml: str,
    ) -> None:
        hub_file = _write(tmp_path / "source" / ".pre-commit-config.yaml", hub_config_yaml)
        target_dir = tmp_path / "target"
        _write(target_dir / LOCAL_OVERLAY, overlay_yaml)
        output = target_dir / ".pre-commit-config.yaml"

        merge_precommit_config(hub_config=hub_file, target_dir=target_dir, output=output)

        content = output.read_text(encoding="utf-8")
        # Document start marker should appear after the generated header
        lines = content.split("\n")
        non_comment_lines = [line for line in lines if not line.startswith("#") and line.strip()]
        assert non_comment_lines[0] == "---"

    def test_merged_output_has_document_end_marker(
        self,
        tmp_path: Path,
        hub_config_yaml: str,
        overlay_yaml: str,
    ) -> None:
        hub_file = _write(tmp_path / "source" / ".pre-commit-config.yaml", hub_config_yaml)
        target_dir = tmp_path / "target"
        _write(target_dir / LOCAL_OVERLAY, overlay_yaml)
        output = target_dir / ".pre-commit-config.yaml"

        merge_precommit_config(hub_config=hub_file, target_dir=target_dir, output=output)

        content = output.read_text(encoding="utf-8").rstrip("\n")
        assert content.endswith("...")

    def test_merged_sequences_are_indented(
        self,
        tmp_path: Path,
        hub_config_yaml: str,
        overlay_yaml: str,
    ) -> None:
        """List items under repos: should be indented (not flush with parent key)."""
        hub_file = _write(tmp_path / "source" / ".pre-commit-config.yaml", hub_config_yaml)
        target_dir = tmp_path / "target"
        _write(target_dir / LOCAL_OVERLAY, overlay_yaml)
        output = target_dir / ".pre-commit-config.yaml"

        merge_precommit_config(hub_config=hub_file, target_dir=target_dir, output=output)

        content = output.read_text(encoding="utf-8")
        # After "repos:" line, list items should be indented (yamllint indent-sequences)
        lines = content.split("\n")
        repos_idx = next(idx for idx, line in enumerate(lines) if line.strip() == "repos:")
        first_item_line = lines[repos_idx + 1]
        assert first_item_line.startswith("  -"), f"Expected indented list item, got: {first_item_line!r}"

    def test_merged_output_roundtrip_valid_yaml(
        self,
        tmp_path: Path,
        hub_config_yaml: str,
        overlay_yaml: str,
    ) -> None:
        hub_file = _write(tmp_path / "source" / ".pre-commit-config.yaml", hub_config_yaml)
        target_dir = tmp_path / "target"
        _write(target_dir / LOCAL_OVERLAY, overlay_yaml)
        output = target_dir / ".pre-commit-config.yaml"

        merge_precommit_config(hub_config=hub_file, target_dir=target_dir, output=output)

        parsed = yaml.safe_load(output.read_text(encoding="utf-8"))
        assert isinstance(parsed, dict)
        assert len(parsed["repos"]) == 3

    def test_passthrough_preserves_original_formatting(
        self,
        tmp_path: Path,
        hub_config_yaml: str,
    ) -> None:
        """Passthrough mode copies verbatim — no reformatting."""
        hub_file = _write(tmp_path / "source" / ".pre-commit-config.yaml", hub_config_yaml)
        output = tmp_path / "target" / ".pre-commit-config.yaml"
        output.parent.mkdir(parents=True, exist_ok=True)

        merge_precommit_config(hub_config=hub_file, target_dir=tmp_path / "target", output=output)

        assert output.read_text(encoding="utf-8") == hub_config_yaml

    def test_anchor_keys_stripped_in_indented_output(
        self,
        tmp_path: Path,
        hub_config_yaml: str,
        overlay_yaml: str,
    ) -> None:
        hub_file = _write(tmp_path / "source" / ".pre-commit-config.yaml", hub_config_yaml)
        target_dir = tmp_path / "target"
        _write(target_dir / LOCAL_OVERLAY, overlay_yaml)
        output = target_dir / ".pre-commit-config.yaml"

        merge_precommit_config(hub_config=hub_file, target_dir=target_dir, output=output)

        content = output.read_text(encoding="utf-8")
        assert "x-python-wrapper" not in content

    def test_nested_args_list_indented(
        self,
        tmp_path: Path,
        hub_config_yaml: str,
        overlay_yaml: str,
    ) -> None:
        """Nested lists (e.g. args under hooks) should also be indented."""
        hub_file = _write(tmp_path / "source" / ".pre-commit-config.yaml", hub_config_yaml)
        target_dir = tmp_path / "target"
        _write(target_dir / LOCAL_OVERLAY, overlay_yaml)
        output = target_dir / ".pre-commit-config.yaml"

        merge_precommit_config(hub_config=hub_file, target_dir=target_dir, output=output)

        content = output.read_text(encoding="utf-8")
        # args list items should be indented under their parent key
        for line in content.split("\n"):
            stripped = line.lstrip()
            if stripped.startswith("- ") and "args" not in stripped:
                indent = len(line) - len(stripped)
                assert indent >= 2, f"List item not indented: {line!r}"
