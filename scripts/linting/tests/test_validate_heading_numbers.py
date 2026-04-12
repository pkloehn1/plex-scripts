"""Tests for scripts.linting.validate_heading_numbers."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.linting.validate_heading_numbers import (
    HeadingIssue,
    _HeadingState,
    _issue_type,
    _iter_files,
    _match_heading,
    _plural,
    _process_files,
    _summarize_issues,
    format_heading_number,
    main,
    parse_heading_number,
    validate_file,
)


class TestMatchHeading:
    def test_level_2(self) -> None:
        result = _match_heading("## 1. First Section")
        assert result is not None
        level, num_str, title, hashes = result
        assert level == 2
        assert num_str == "1."
        assert title == "First Section"
        assert hashes == "##"

    def test_level_3(self) -> None:
        result = _match_heading("### 1.1 Subsection")
        assert result is not None
        assert result[0] == 3

    def test_not_a_heading(self) -> None:
        assert _match_heading("Some regular text") is None

    def test_level_1_ignored(self) -> None:
        assert _match_heading("# 1. Title") is None

    def test_level_7_ignored(self) -> None:
        assert _match_heading("####### 1. Title") is None

    def test_no_space_after_hashes(self) -> None:
        assert _match_heading("##NoSpace") is None

    def test_no_title(self) -> None:
        assert _match_heading("## 1.") is None

    def test_non_numeric(self) -> None:
        assert _match_heading("## abc. Title") is None

    def test_too_many_segments(self) -> None:
        assert _match_heading("## 1.2.3.4.5.6.7 Title") is None

    def test_tab_after_hashes(self) -> None:
        result = _match_heading("##\t1. Title")
        assert result is not None

    def test_level_6(self) -> None:
        result = _match_heading("###### 1.2.3.4.5 Deep")
        assert result is not None
        assert result[0] == 6

    def test_no_trailing_dot(self) -> None:
        result = _match_heading("## 1 Section")
        assert result is not None
        assert result[1] == "1"


class TestHeadingState:
    def test_section_sequence(self) -> None:
        state = _HeadingState()
        assert state.expected_for(2, [1]) == [1]
        assert state.expected_for(2, [2]) == [2]
        assert state.expected_for(2, [3]) == [3]

    def test_subsection_sequence(self) -> None:
        state = _HeadingState()
        state.expected_for(2, [1])  # section 1
        assert state.expected_for(3, [1, 1]) == [1, 1]
        assert state.expected_for(3, [1, 2]) == [1, 2]

    def test_subsection_reset_on_new_section(self) -> None:
        state = _HeadingState()
        state.expected_for(2, [1])
        state.expected_for(3, [1, 1])
        state.expected_for(2, [2])  # new section
        assert state.expected_for(3, [2, 1]) == [2, 1]

    def test_deeper_counters_reset(self) -> None:
        state = _HeadingState()
        state.expected_for(2, [1])
        state.expected_for(3, [1, 1])
        state.expected_for(4, [1, 1, 1])
        state.expected_for(3, [1, 2])  # should reset level 4
        assert state.expected_for(4, [1, 2, 1]) == [1, 2, 1]

    def test_parent_prefix_fallback_multi_segment(self) -> None:
        state = _HeadingState()
        # Jump to level 4 without proper parent chain
        result = state.expected_for(4, [1, 2, 3])
        # Should fall back to actual_nums[:-1]
        assert result == [1, 2, 1]

    def test_parent_prefix_fallback_single_segment(self) -> None:
        state = _HeadingState()
        # Level 3 with single-segment number and no parent — returns []
        result = state.expected_for(3, [5])
        assert result == [1]


class TestIssueType:
    def test_sequence(self) -> None:
        assert _issue_type([3], [2]) == "sequence"

    def test_parent_mismatch(self) -> None:
        assert _issue_type([2, 1], [1, 1]) == "parent_mismatch"

    def test_subsection_sequence(self) -> None:
        assert _issue_type([1, 3], [1, 2]) == "subsection_sequence"


class TestParseHeadingNumber:
    def test_simple(self) -> None:
        assert parse_heading_number("1") == [1]

    def test_dotted(self) -> None:
        assert parse_heading_number("1.2.3") == [1, 2, 3]

    def test_trailing_dot(self) -> None:
        assert parse_heading_number("1.2.") == [1, 2]


class TestFormatHeadingNumber:
    def test_simple(self) -> None:
        assert format_heading_number([1]) == "1"

    def test_dotted(self) -> None:
        assert format_heading_number([1, 2, 3]) == "1.2.3"

    def test_trailing_dot(self) -> None:
        assert format_heading_number([1, 2], trailing_dot=True) == "1.2."


class TestValidateFile:
    def test_valid_file(self, tmp_path: Path) -> None:
        mdfile = tmp_path / "ok.md"
        mdfile.write_text("# Title\n\n## 1. One\n\n### 1.1 Sub\n\n## 2. Two\n", encoding="utf-8")
        issues = validate_file(mdfile)
        assert issues == []

    def test_sequence_issue(self, tmp_path: Path) -> None:
        mdfile = tmp_path / "bad.md"
        mdfile.write_text("# Title\n\n## 1. One\n\n## 3. Skipped\n", encoding="utf-8")
        issues = validate_file(mdfile)
        assert len(issues) == 1
        assert issues[0].issue_type == "sequence"
        assert issues[0].expected == "2."
        assert issues[0].actual == "3."

    def test_parent_mismatch(self, tmp_path: Path) -> None:
        mdfile = tmp_path / "bad.md"
        mdfile.write_text("# Title\n\n## 1. One\n\n### 2.1 Wrong\n", encoding="utf-8")
        issues = validate_file(mdfile)
        assert any(i.issue_type == "parent_mismatch" for i in issues)

    def test_fix_mode(self, tmp_path: Path) -> None:
        mdfile = tmp_path / "fix.md"
        mdfile.write_text("# Title\n\n## 1. One\n\n## 3. Skipped\n", encoding="utf-8")
        issues = validate_file(mdfile, fix=True)
        assert len(issues) == 1
        content = mdfile.read_text(encoding="utf-8")
        assert "## 2. Skipped" in content

    def test_no_newline_at_end(self, tmp_path: Path) -> None:
        mdfile = tmp_path / "no_nl.md"
        mdfile.write_text("# Title\n\n## 1. One\n\n## 3. Skipped", encoding="utf-8")
        issues = validate_file(mdfile, fix=True)
        assert len(issues) == 1
        content = mdfile.read_text(encoding="utf-8")
        assert "## 2. Skipped" in content

    def test_non_heading_lines_preserved(self, tmp_path: Path) -> None:
        mdfile = tmp_path / "mixed.md"
        mdfile.write_text("# Title\n\nSome text\n\n## 1. One\n\nMore text\n", encoding="utf-8")
        issues = validate_file(mdfile)
        assert issues == []

    def test_no_trailing_dot(self, tmp_path: Path) -> None:
        mdfile = tmp_path / "no_dot.md"
        mdfile.write_text("# Title\n\n## 1 One\n\n## 3 Skipped\n", encoding="utf-8")
        issues = validate_file(mdfile)
        assert len(issues) == 1
        assert issues[0].expected == "2"


class TestPlural:
    def test_singular(self) -> None:
        assert _plural(1, "file") == "file"

    def test_plural_default(self) -> None:
        assert _plural(2, "file") == "files"

    def test_plural_custom(self) -> None:
        assert _plural(0, "ox", "oxen") == "oxen"


class TestSummarizeIssues:
    def test_sequence_issues(self) -> None:
        issues = [
            HeadingIssue(1, "## 3.", "2.", "3.", "sequence"),
            HeadingIssue(2, "## 5.", "4.", "5.", "sequence"),
        ]
        result = _summarize_issues(issues)
        assert "sequence=2" in result

    def test_mixed_types(self) -> None:
        issues = [
            HeadingIssue(1, "", "", "", "sequence"),
            HeadingIssue(2, "", "", "", "parent_mismatch"),
        ]
        result = _summarize_issues(issues)
        assert "sequence=1" in result
        assert "parent_mismatch=1" in result

    def test_empty(self) -> None:
        assert _summarize_issues([]) == "(no issue types)"

    def test_unknown_type(self) -> None:
        issues = [HeadingIssue(1, "", "", "", "custom_type")]
        result = _summarize_issues(issues)
        assert "custom_type=1" in result


class TestIterFiles:
    def test_explicit_files(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.md"
        f.write_text("# Title\n", encoding="utf-8")
        result = _iter_files([f])
        assert result == [f]

    def test_no_files_no_docs_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = _iter_files([])
        assert result == []

    def test_auto_discover_docs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        docs = tmp_path / "docs"
        docs.mkdir()
        mdfile = docs / "page.md"
        mdfile.write_text("# Title\n", encoding="utf-8")
        result = _iter_files([])
        assert len(result) == 1


class TestProcessFiles:
    def test_missing_file(self, tmp_path: Path, capsys: object) -> None:
        result = _process_files([tmp_path / "missing.md"], fix=False)
        assert result.checked_files == 0
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert "does not exist" in captured.out

    def test_valid_no_issues(self, tmp_path: Path) -> None:
        mdfile = tmp_path / "ok.md"
        mdfile.write_text("# Title\n\n## 1. One\n\n## 2. Two\n", encoding="utf-8")
        result = _process_files([mdfile], fix=False)
        assert result.checked_files == 1
        assert result.total_issues == 0

    def test_with_issues(self, tmp_path: Path) -> None:
        mdfile = tmp_path / "bad.md"
        mdfile.write_text("# Title\n\n## 1. One\n\n## 3. Skipped\n", encoding="utf-8")
        result = _process_files([mdfile], fix=False)
        assert result.total_issues == 1

    def test_with_fix(self, tmp_path: Path) -> None:
        mdfile = tmp_path / "fix.md"
        mdfile.write_text("# Title\n\n## 1. One\n\n## 3. Skipped\n", encoding="utf-8")
        result = _process_files([mdfile], fix=True)
        assert result.total_issues == 1

    def test_error_file(self, tmp_path: Path) -> None:
        mdfile = tmp_path / "binary.md"
        mdfile.write_bytes(b"\xff\xfe\xff\n")
        result = _process_files([mdfile], fix=False)
        assert result.total_error_files == 1

    def test_single_issue_label(self, tmp_path: Path, capsys: object) -> None:
        mdfile = tmp_path / "one.md"
        mdfile.write_text("# Title\n\n## 2. Wrong\n", encoding="utf-8")
        _process_files([mdfile], fix=False)
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert "1 issue" in captured.out


class TestMain:
    def test_no_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: object) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sys.argv", ["validate", "--fix"])
        code = main()
        assert code == 0
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert "No markdown files" in captured.out

    def test_pass(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mdfile = tmp_path / "ok.md"
        mdfile.write_text("# Title\n\n## 1. One\n\n## 2. Two\n", encoding="utf-8")
        monkeypatch.setattr("sys.argv", ["validate", str(mdfile)])
        code = main()
        assert code == 0

    def test_fail(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: object) -> None:
        mdfile = tmp_path / "bad.md"
        mdfile.write_text("# Title\n\n## 1. One\n\n## 3. Skipped\n", encoding="utf-8")
        monkeypatch.setattr("sys.argv", ["validate", str(mdfile)])
        code = main()
        assert code == 1
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert "FAIL:" in captured.out

    def test_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mdfile = tmp_path / "binary.md"
        mdfile.write_bytes(b"\xff\xfe\xff\n")
        monkeypatch.setattr("sys.argv", ["validate", str(mdfile)])
        code = main()
        assert code == 2

    def test_fix(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: object) -> None:
        mdfile = tmp_path / "fix.md"
        mdfile.write_text("# Title\n\n## 1. One\n\n## 3. Skipped\n", encoding="utf-8")
        monkeypatch.setattr("sys.argv", ["validate", "--fix", str(mdfile)])
        code = main()
        assert code == 0
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert "fixed" in captured.out

    def test_fix_no_issues(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: object) -> None:
        mdfile = tmp_path / "ok.md"
        mdfile.write_text("# Title\n\n## 1. One\n\n## 2. Two\n", encoding="utf-8")
        monkeypatch.setattr("sys.argv", ["validate", "--fix", str(mdfile)])
        code = main()
        assert code == 0
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert "fixed 0" in captured.out

    def test_fail_multiple_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: object) -> None:
        mdfile = tmp_path / "bad.md"
        mdfile.write_text("# Title\n\n## 1. One\n\n## 3. Skipped\n", encoding="utf-8")
        monkeypatch.setattr("sys.argv", ["validate", str(mdfile)])
        code = main()
        assert code == 1
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert "1 file" in captured.out

    def test_error_plural(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: object) -> None:
        md1 = tmp_path / "a.md"
        md2 = tmp_path / "b.md"
        md1.write_bytes(b"\xff\xfe\xff\n")
        md2.write_bytes(b"\xff\xfe\xff\n")
        monkeypatch.setattr("sys.argv", ["validate", str(md1), str(md2)])
        code = main()
        assert code == 2
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert "2 files" in captured.out
