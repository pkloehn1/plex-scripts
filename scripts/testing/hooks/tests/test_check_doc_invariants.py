from __future__ import annotations

import scripts.testing.hooks.check_doc_invariants as mod
from scripts.testing.hooks.conftest import (
    assert_read_file_error,
    assert_staged_paths_error,
    fake_file_lines_reader,
    fake_staged_paths,
)


def test_runbook_missing_sections(monkeypatch, capsys):
    monkeypatch.setattr(mod, "_get_staged_paths", lambda: fake_staged_paths(["docs/automation/runbooks/a.md"]))
    monkeypatch.setattr(
        mod,
        "_read_staged_file",
        fake_file_lines_reader({"docs/automation/runbooks/a.md": "# Title\n## 1. Purpose\n"}),
    )

    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "Runbook must include numbered sections" in err


def test_runbook_ok(monkeypatch):
    monkeypatch.setattr(mod, "_get_staged_paths", lambda: fake_staged_paths(["docs/automation/runbooks/a.md"]))
    monkeypatch.setattr(
        mod,
        "_read_staged_file",
        fake_file_lines_reader({"docs/automation/runbooks/a.md": "# Title\n## 1. Purpose\n## 2. Scope\n"}),
    )

    assert mod.main() == 0


def test_arch_doc_missing_subheading(monkeypatch, capsys):
    monkeypatch.setattr(mod, "_get_staged_paths", lambda: fake_staged_paths(["docs/architecture/diag.md"]))
    monkeypatch.setattr(
        mod,
        "_read_staged_file",
        fake_file_lines_reader({"docs/architecture/diag.md": "# Diagram\n"}),
    )

    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "Architecture doc must include at least one '## '" in err


def test_arch_doc_ok(monkeypatch):
    monkeypatch.setattr(mod, "_get_staged_paths", lambda: fake_staged_paths(["docs/architecture/diag.md"]))
    monkeypatch.setattr(
        mod,
        "_read_staged_file",
        fake_file_lines_reader({"docs/architecture/diag.md": "# Diagram\n## Detail\n"}),
    )

    assert mod.main() == 0


def test_non_target_file_ignored(monkeypatch):
    monkeypatch.setattr(mod, "_get_staged_paths", lambda: fake_staged_paths(["README.md"]))

    assert mod.main() == 0


def test_get_staged_paths_git_error(monkeypatch, capsys):
    """_get_staged_paths() returns error when git diff fails."""
    assert_staged_paths_error(mod, monkeypatch, capsys)


def test_read_staged_file_git_error(monkeypatch, capsys):
    """_read_staged_file() returns error when git show fails."""
    assert_read_file_error(mod, monkeypatch, capsys, "_get_staged_paths", ["docs/automation/runbooks/a.md"])


def test_runbook_missing_top_heading(monkeypatch, capsys):
    """Runbook without top-level heading fails validation."""
    monkeypatch.setattr(mod, "_get_staged_paths", lambda: fake_staged_paths(["docs/automation/runbooks/a.md"]))
    monkeypatch.setattr(
        mod,
        "_read_staged_file",
        fake_file_lines_reader({"docs/automation/runbooks/a.md": "## 1. Purpose\n## 2. Scope\n"}),
    )

    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "must start with a top-level '# ' heading" in err


def test_runbook_empty_file(monkeypatch, capsys):
    """Runbook with only whitespace fails validation."""
    monkeypatch.setattr(mod, "_get_staged_paths", lambda: fake_staged_paths(["docs/automation/runbooks/a.md"]))
    monkeypatch.setattr(
        mod,
        "_read_staged_file",
        fake_file_lines_reader({"docs/automation/runbooks/a.md": "\n  \n\t\n"}),
    )

    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "must start with a top-level '# ' heading" in err


def test_arch_doc_missing_top_heading(monkeypatch, capsys):
    """Architecture doc without top-level heading fails validation."""
    monkeypatch.setattr(mod, "_get_staged_paths", lambda: fake_staged_paths(["docs/architecture/diag.md"]))
    monkeypatch.setattr(
        mod,
        "_read_staged_file",
        fake_file_lines_reader({"docs/architecture/diag.md": "## Detail\n"}),
    )

    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "must start with a top-level '# ' heading" in err


def test_read_staged_file_returns_none_lines(monkeypatch, capsys):
    """main() handles None lines from _read_staged_file."""
    monkeypatch.setattr(mod, "_get_staged_paths", lambda: fake_staged_paths(["docs/automation/runbooks/a.md"]))

    def fake_reader_none(path):
        return None, None

    monkeypatch.setattr(mod, "_read_staged_file", fake_reader_none)
    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "Unable to read staged file content" in err


def test_non_runbook_non_arch_doc_not_validated(monkeypatch):
    """Non-target markdown files in docs/ are skipped."""
    monkeypatch.setattr(mod, "_get_staged_paths", lambda: fake_staged_paths(["docs/README.md", "docs/setup.md"]))
    monkeypatch.setattr(
        mod,
        "_read_staged_file",
        fake_file_lines_reader({"docs/README.md": "No heading", "docs/setup.md": "No heading"}),
    )

    assert mod.main() == 0


def test_collect_violations_non_target_path():
    """_collect_violations returns empty list for non-runbook, non-architecture files."""
    from pathlib import Path

    assert mod._collect_violations(Path("docs/README.md"), ["# Heading", "content"]) == []


def test_read_staged_file_wrapper_success(monkeypatch):
    """Module-level _read_staged_file returns splitlines on success."""
    from pathlib import Path

    monkeypatch.setattr(mod, "read_staged_file", lambda _path: ("line1\nline2\nline3", None))
    lines, err = mod._read_staged_file(Path("docs/automation/runbooks/a.md"))
    assert err is None
    assert lines == ["line1", "line2", "line3"]


def test_read_staged_file_wrapper_error(monkeypatch):
    """Module-level _read_staged_file propagates errors."""
    from pathlib import Path

    monkeypatch.setattr(mod, "read_staged_file", lambda _path: (None, "git show failed"))
    lines, err = mod._read_staged_file(Path("docs/automation/runbooks/a.md"))
    assert lines is None
    assert err == "git show failed"


def test_read_staged_file_wrapper_none_content(monkeypatch):
    """Module-level _read_staged_file returns (None, None) when content is None without error."""
    from pathlib import Path

    monkeypatch.setattr(mod, "read_staged_file", lambda _path: (None, None))
    lines, err = mod._read_staged_file(Path("docs/automation/runbooks/a.md"))
    assert lines is None
    assert err is None
