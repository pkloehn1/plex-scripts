"""Tests for validate_service_sheets.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.linting.validate_service_sheets import (
    _detect_template_type,
    _extract_h2_headings,
    _find_repo_root,
    _iter_service_sheets,
    _load_template,
    main,
    validate_sheet,
)

# ---------------------------------------------------------------------------
# _detect_template_type
# ---------------------------------------------------------------------------


def test_detect_template_type_group():
    assert _detect_template_type("<!-- template: group -->") == "group"


def test_detect_template_type_single():
    assert _detect_template_type("<!-- template: single -->") == "single"


def test_detect_template_type_missing():
    assert _detect_template_type("# No template comment here") is None


def test_detect_template_type_extra_whitespace():
    assert _detect_template_type("<!--  template:  group  -->") == "group"


def test_detect_template_type_embedded_in_content():
    text = "# Title\nSome text\n<!-- template: single -->\nMore text"
    assert _detect_template_type(text) == "single"


# ---------------------------------------------------------------------------
# _extract_h2_headings
# ---------------------------------------------------------------------------


def test_extract_h2_headings():
    text = "# Title\n## Sources\nSome text\n## Config\n### Sub\n## Rollback"
    assert _extract_h2_headings(text) == ["Sources", "Config", "Rollback"]


def test_extract_h2_headings_empty():
    assert _extract_h2_headings("# Just a title\nNo headings here.") == []


def test_extract_h2_headings_ignores_h1_h3():
    text = "# H1\n## H2 One\n### H3\n#### H4\n## H2 Two"
    assert _extract_h2_headings(text) == ["H2 One", "H2 Two"]


# ---------------------------------------------------------------------------
# _load_template
# ---------------------------------------------------------------------------


def test_load_template_returns_headings(tmp_path: Path):
    services_dir = tmp_path / "docs" / "inventory" / "services"
    services_dir.mkdir(parents=True)
    template = services_dir / "_template-group.md"
    template.write_text("# Template\n<!-- template: group -->\n## Alpha\n## Beta\n")

    result = _load_template("group", tmp_path)
    assert result == ["Alpha", "Beta"]


def test_load_template_returns_none_when_missing(tmp_path: Path):
    result = _load_template("group", tmp_path)
    assert result is None


# ---------------------------------------------------------------------------
# validate_sheet
# ---------------------------------------------------------------------------


def test_valid_sheet_passes(tmp_path: Path):
    template = tmp_path / "docs" / "inventory" / "services" / "_template-single.md"
    template.parent.mkdir(parents=True)
    template.write_text("# Template\n<!-- template: single -->\n## Alpha\n## Beta\n")

    sheet = tmp_path / "docs" / "inventory" / "services" / "test-service.md"
    sheet.write_text("# Test\n<!-- template: single -->\n## Alpha\nContent\n## Beta\nContent\n")

    findings = validate_sheet(sheet, tmp_path)
    assert findings == []


def test_missing_section_detected(tmp_path: Path):
    template = tmp_path / "docs" / "inventory" / "services" / "_template-single.md"
    template.parent.mkdir(parents=True)
    template.write_text("# Template\n<!-- template: single -->\n## Alpha\n## Beta\n")

    sheet = tmp_path / "docs" / "inventory" / "services" / "test-service.md"
    sheet.write_text("# Test\n<!-- template: single -->\n## Alpha\nContent\n")

    findings = validate_sheet(sheet, tmp_path)
    assert len(findings) == 1
    assert "Missing required section: ## Beta" in findings[0].message


def test_extra_section_detected(tmp_path: Path):
    template = tmp_path / "docs" / "inventory" / "services" / "_template-single.md"
    template.parent.mkdir(parents=True)
    template.write_text("# Template\n<!-- template: single -->\n## Alpha\n")

    sheet = tmp_path / "docs" / "inventory" / "services" / "test-service.md"
    sheet.write_text("# Test\n<!-- template: single -->\n## Alpha\n## Extra\n")

    findings = validate_sheet(sheet, tmp_path)
    assert len(findings) == 1
    assert "Extra section not in template: ## Extra" in findings[0].message


def test_wrong_order_detected(tmp_path: Path):
    template = tmp_path / "docs" / "inventory" / "services" / "_template-single.md"
    template.parent.mkdir(parents=True)
    template.write_text("# Template\n<!-- template: single -->\n## Alpha\n## Beta\n")

    sheet = tmp_path / "docs" / "inventory" / "services" / "test-service.md"
    sheet.write_text("# Test\n<!-- template: single -->\n## Beta\n## Alpha\n")

    findings = validate_sheet(sheet, tmp_path)
    assert any("order does not match" in finding.message for finding in findings)


def test_missing_template_comment(tmp_path: Path):
    sheet = tmp_path / "no-comment.md"
    sheet.write_text("# Test\n## Alpha\n")

    findings = validate_sheet(sheet, tmp_path)
    assert len(findings) == 1
    assert "Missing template declaration" in findings[0].message


def test_template_file_not_found(tmp_path: Path):
    sheet = tmp_path / "orphan.md"
    sheet.write_text("# Test\n<!-- template: group -->\n## Alpha\n")

    findings = validate_sheet(sheet, tmp_path)
    assert len(findings) == 1
    assert "Template file _template-group.md not found" in findings[0].message


# ---------------------------------------------------------------------------
# _find_repo_root
# ---------------------------------------------------------------------------


def test_find_repo_root_finds_git_dir(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    with patch("scripts.linting.validate_service_sheets.Path.cwd", return_value=tmp_path):
        assert _find_repo_root() == tmp_path


def test_find_repo_root_walks_up(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    child = tmp_path / "sub" / "deep"
    child.mkdir(parents=True)
    with patch("scripts.linting.validate_service_sheets.Path.cwd", return_value=child):
        assert _find_repo_root() == tmp_path


def test_find_repo_root_fallback_to_cwd(tmp_path: Path):
    bare = tmp_path / "no-git"
    bare.mkdir()
    with patch("scripts.linting.validate_service_sheets.Path.cwd", return_value=bare):
        result = _find_repo_root()
        assert result == bare


# ---------------------------------------------------------------------------
# _iter_service_sheets
# ---------------------------------------------------------------------------


def test_iter_service_sheets_returns_non_templates(tmp_path: Path):
    services_dir = tmp_path / "docs" / "inventory" / "services"
    services_dir.mkdir(parents=True)
    (services_dir / "_template-group.md").write_text("# Template\n")
    (services_dir / "_template-single.md").write_text("# Template\n")
    (services_dir / "gravitee-apim.md").write_text("# Gravitee\n")
    (services_dir / "sonarr.md").write_text("# Sonarr\n")

    result = _iter_service_sheets(tmp_path)
    names = [path.name for path in result]
    assert "_template-group.md" not in names
    assert "_template-single.md" not in names
    assert "gravitee-apim.md" in names
    assert "sonarr.md" in names


def test_iter_service_sheets_empty_when_no_dir(tmp_path: Path):
    assert _iter_service_sheets(tmp_path) == []


# ---------------------------------------------------------------------------
# main (CLI)
# ---------------------------------------------------------------------------


def _setup_valid_repo(tmp_path: Path) -> Path:
    """Create a minimal valid repo structure for main() tests."""
    services_dir = tmp_path / "docs" / "inventory" / "services"
    services_dir.mkdir(parents=True)
    (tmp_path / ".git").mkdir()
    (services_dir / "_template-single.md").write_text("# Template\n<!-- template: single -->\n## Alpha\n## Beta\n")
    return services_dir


def test_main_no_files_returns_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["validate_service_sheets.py"])
    assert main() == 0


def test_main_valid_file_returns_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    services_dir = _setup_valid_repo(tmp_path)
    sheet = services_dir / "test-svc.md"
    sheet.write_text("# Test\n<!-- template: single -->\n## Alpha\n## Beta\n")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["validate_service_sheets.py", str(sheet)])
    assert main() == 0


def test_main_invalid_file_returns_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    services_dir = _setup_valid_repo(tmp_path)
    sheet = services_dir / "bad-svc.md"
    sheet.write_text("# Test\n<!-- template: single -->\n## Alpha\n")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["validate_service_sheets.py", str(sheet)])
    assert main() == 1


def test_main_missing_file_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["validate_service_sheets.py", "/nonexistent/file.md"])
    assert main() == 0
    assert "WARNING" in capsys.readouterr().out


def test_main_exception_returns_two(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / ".git").mkdir()
    unreadable = tmp_path / "unreadable.md"
    unreadable.write_text("content")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["validate_service_sheets.py", str(unreadable)])

    def _raise(*_args, **_kwargs):
        raise OSError("Permission denied")

    monkeypatch.setattr(
        "scripts.linting.validate_service_sheets.validate_sheet",
        _raise,
    )
    assert main() == 2


def test_main_auto_discovers_sheets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    services_dir = _setup_valid_repo(tmp_path)
    sheet = services_dir / "my-service.md"
    sheet.write_text("# My Service\n<!-- template: single -->\n## Alpha\n## Beta\n")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["validate_service_sheets.py"])
    assert main() == 0


def test_main_plural_label(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    services_dir = _setup_valid_repo(tmp_path)
    (services_dir / "svc-a.md").write_text("# A\n<!-- template: single -->\n## Alpha\n## Beta\n")
    (services_dir / "svc-b.md").write_text("# B\n<!-- template: single -->\n## Alpha\n## Beta\n")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["validate_service_sheets.py"])
    assert main() == 0
    assert "2 service files" in capsys.readouterr().out


def test_main_singular_label(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    services_dir = _setup_valid_repo(tmp_path)
    (services_dir / "svc-a.md").write_text("# A\n<!-- template: single -->\n## Alpha\n## Beta\n")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["validate_service_sheets.py"])
    assert main() == 0
    assert "1 service file" in capsys.readouterr().out


def test_main_finding_relative_path_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / ".git").mkdir()
    services_dir = tmp_path / "docs" / "inventory" / "services"
    services_dir.mkdir(parents=True)
    (services_dir / "_template-single.md").write_text("# Template\n<!-- template: single -->\n## Alpha\n")

    # Create sheet outside repo root to trigger ValueError on relative_to.
    outside_dir = tmp_path.parent / "outside"
    outside_dir.mkdir(exist_ok=True)
    outside = outside_dir / "test-outside-sheet.md"
    outside.write_text("# Test\n<!-- template: single -->\n## Alpha\n## Extra\n")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["validate_service_sheets.py", str(outside)])
    assert main() == 1
