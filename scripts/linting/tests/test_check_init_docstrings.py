"""Tests for scripts.linting.check_init_docstrings."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts.linting.check_init_docstrings import (
    _check_init_file,
    _get_docstring,
    _is_test_package,
    _repo_root,
    find_violations,
    main,
)

_MOD = "scripts.linting.check_init_docstrings"


class TestRepoRoot:
    def test_returns_path(self) -> None:
        result = _repo_root()
        assert isinstance(result, Path)
        assert (result / "pyproject.toml").exists()


class TestGetDocstring:
    def test_valid_source(self) -> None:
        assert _get_docstring('"""Hello."""\n') == "Hello."

    def test_no_docstring(self) -> None:
        assert _get_docstring("x = 1\n") is None

    def test_syntax_error(self) -> None:
        assert _get_docstring("def f(\n") is None


class TestIsTestPackage:
    def test_tests_dir(self, tmp_path: Path) -> None:
        init = tmp_path / "tests" / "__init__.py"
        init.parent.mkdir()
        assert _is_test_package(init) is True

    def test_non_test_dir(self, tmp_path: Path) -> None:
        init = tmp_path / "utils" / "__init__.py"
        init.parent.mkdir()
        assert _is_test_package(init) is False


class TestCheckInitFile:
    def test_missing_file(self, tmp_path: Path) -> None:
        result = _check_init_file(tmp_path / "__init__.py")
        assert result is not None
        assert "does not exist" in result.message

    def test_comment_instead_of_docstring(self, tmp_path: Path) -> None:
        init = tmp_path / "__init__.py"
        init.write_text("# This is a comment\n", encoding="utf-8")
        result = _check_init_file(init)
        assert result is not None
        assert "comment instead of docstring" in result.message

    def test_no_docstring(self, tmp_path: Path) -> None:
        init = tmp_path / "__init__.py"
        init.write_text("x = 1\n", encoding="utf-8")
        result = _check_init_file(init)
        assert result is not None
        assert "Missing module docstring" in result.message

    def test_valid_docstring(self, tmp_path: Path) -> None:
        init = tmp_path / "__init__.py"
        init.write_text('"""My package."""\n', encoding="utf-8")
        assert _check_init_file(init) is None

    def test_test_package_wrong_prefix(self, tmp_path: Path) -> None:
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        init = tests_dir / "__init__.py"
        init.write_text('"""Wrong prefix."""\n', encoding="utf-8")
        result = _check_init_file(init)
        assert result is not None
        assert "Tests for" in result.message

    def test_test_package_correct_prefix(self, tmp_path: Path) -> None:
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        init = tests_dir / "__init__.py"
        init.write_text('"""Tests for my package."""\n', encoding="utf-8")
        assert _check_init_file(init) is None


class TestFindViolations:
    def test_with_violations(self, tmp_path: Path) -> None:
        scripts_dir = tmp_path / "scripts"
        pkg = scripts_dir / "mypkg"
        pkg.mkdir(parents=True)
        init = pkg / "__init__.py"
        init.write_text("x = 1\n", encoding="utf-8")

        with patch(f"{_MOD}._repo_root", return_value=tmp_path):
            findings = find_violations()
        assert len(findings) == 1

    def test_no_scripts_dir(self, tmp_path: Path) -> None:
        with patch(f"{_MOD}._repo_root", return_value=tmp_path):
            findings = find_violations()
        assert len(findings) == 1
        assert "scripts/ directory not found" in findings[0].message


class TestMain:
    def test_pass(self, tmp_path: Path, capsys: object) -> None:
        scripts_dir = tmp_path / "scripts"
        pkg = scripts_dir / "mypkg"
        pkg.mkdir(parents=True)
        init = pkg / "__init__.py"
        init.write_text('"""My package."""\n', encoding="utf-8")

        with patch(f"{_MOD}._repo_root", return_value=tmp_path):
            code = main()
        assert code == 0
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert "PASS" in captured.out

    def test_fail(self, tmp_path: Path, capsys: object) -> None:
        scripts_dir = tmp_path / "scripts"
        pkg = scripts_dir / "mypkg"
        pkg.mkdir(parents=True)
        init = pkg / "__init__.py"
        init.write_text("x = 1\n", encoding="utf-8")

        with patch(f"{_MOD}._repo_root", return_value=tmp_path):
            code = main()
        assert code == 1
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert "FAIL" in captured.out
