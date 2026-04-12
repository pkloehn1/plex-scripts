"""Tests for git_utils module."""

from pathlib import Path
from unittest.mock import patch

from scripts.context_validator.git_utils import (
    get_baseline_file_sizes,
    get_changed_files,
    get_file_content_from_branch,
)


class _FakeCompletedProcess:
    """Minimal subprocess.CompletedProcess stand-in."""

    def __init__(self, stdout: str = "", returncode: int = 0):
        self.stdout = stdout
        self.returncode = returncode


# ---------------------------------------------------------------------------
# get_changed_files
# ---------------------------------------------------------------------------


class TestGetChangedFiles:
    def test_returns_changed_paths(self, tmp_path: Path):
        fake = _FakeCompletedProcess(stdout="file_a.py\nfile_b.py\n")
        with patch("scripts.context_validator.git_utils.subprocess.run", return_value=fake):
            result = get_changed_files("origin/main", tmp_path)
        assert result == [tmp_path / "file_a.py", tmp_path / "file_b.py"]

    def test_returns_empty_on_error(self, tmp_path: Path):
        import subprocess

        with patch(
            "scripts.context_validator.git_utils.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "git"),
        ):
            result = get_changed_files("origin/main", tmp_path)
        assert result == []

    def test_skips_empty_lines(self, tmp_path: Path):
        fake = _FakeCompletedProcess(stdout="file_a.py\n\n\n")
        with patch("scripts.context_validator.git_utils.subprocess.run", return_value=fake):
            result = get_changed_files("origin/main", tmp_path)
        assert result == [tmp_path / "file_a.py"]

    def test_returns_empty_for_no_changes(self, tmp_path: Path):
        fake = _FakeCompletedProcess(stdout="")
        with patch("scripts.context_validator.git_utils.subprocess.run", return_value=fake):
            result = get_changed_files("origin/main", tmp_path)
        assert result == []


# ---------------------------------------------------------------------------
# get_file_content_from_branch
# ---------------------------------------------------------------------------


class TestGetFileContentFromBranch:
    def test_returns_content(self, tmp_path: Path):
        fake = _FakeCompletedProcess(stdout="hello world")
        with patch("scripts.context_validator.git_utils.subprocess.run", return_value=fake):
            result = get_file_content_from_branch("file.md", "origin/main", tmp_path)
        assert result == "hello world"

    def test_returns_none_on_error(self, tmp_path: Path):
        import subprocess

        with patch(
            "scripts.context_validator.git_utils.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "git"),
        ):
            result = get_file_content_from_branch("missing.md", "origin/main", tmp_path)
        assert result is None


# ---------------------------------------------------------------------------
# get_baseline_file_sizes
# ---------------------------------------------------------------------------


class TestGetBaselineFileSizes:
    def test_returns_file_sizes(self, tmp_path: Path):
        ls_tree = _FakeCompletedProcess(stdout="docs/a.md\ndocs/b.md\nREADME.md\n")

        def fake_run(cmd, **kwargs):
            if "ls-tree" in cmd:
                return ls_tree
            if "show" in cmd:
                # Return content whose length becomes the size
                ref = cmd[-1]  # e.g. "origin/main:docs/a.md"
                if "a.md" in ref:
                    return _FakeCompletedProcess(stdout="short")
                if "b.md" in ref:
                    return _FakeCompletedProcess(stdout="longer content")
                raise ValueError(f"unexpected ref: {ref}")
            raise ValueError(f"unexpected cmd: {cmd}")

        with patch("scripts.context_validator.git_utils.subprocess.run", side_effect=fake_run):
            result = get_baseline_file_sizes(["docs/*.md"], "origin/main", tmp_path)

        assert "docs/*.md" in result
        paths = [name for name, _ in result["docs/*.md"]]
        assert "docs/a.md" in paths
        assert "docs/b.md" in paths

    def test_returns_empty_on_ls_tree_error(self, tmp_path: Path):
        import subprocess

        with patch(
            "scripts.context_validator.git_utils.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "git"),
        ):
            result = get_baseline_file_sizes(["*.md"], "origin/main", tmp_path)
        assert result == {}

    def test_skips_files_not_matching_pattern(self, tmp_path: Path):
        ls_tree = _FakeCompletedProcess(stdout="docs/a.md\nsrc/main.py\n")

        def fake_run(cmd, **kwargs):
            if "ls-tree" in cmd:
                return ls_tree
            if "show" in cmd:
                return _FakeCompletedProcess(stdout="content")
            raise ValueError(f"unexpected cmd: {cmd}")

        with patch("scripts.context_validator.git_utils.subprocess.run", side_effect=fake_run):
            result = get_baseline_file_sizes(["docs/*.md"], "origin/main", tmp_path)

        paths = [name for name, _ in result["docs/*.md"]]
        assert "src/main.py" not in paths

    def test_skips_file_when_show_returns_none(self, tmp_path: Path):
        import subprocess

        ls_tree = _FakeCompletedProcess(stdout="docs/a.md\n")

        call_count = 0

        def fake_run(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            if "ls-tree" in cmd:
                return ls_tree
            # git show fails
            raise subprocess.CalledProcessError(1, "git")

        with patch("scripts.context_validator.git_utils.subprocess.run", side_effect=fake_run):
            result = get_baseline_file_sizes(["docs/*.md"], "origin/main", tmp_path)

        assert result["docs/*.md"] == []
