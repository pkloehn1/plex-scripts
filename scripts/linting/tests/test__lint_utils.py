"""Tests for scripts.linting._lint_utils."""

from __future__ import annotations

from pathlib import Path

from scripts.linting._lint_utils import LintResult, Severity, cli_main, format_result


def _noop_lint(_path: Path) -> list[LintResult]:
    """Lint function that always returns no results."""
    return []


class TestCliMainMissingFiles:
    def test_missing_file_returns_nonzero(self, monkeypatch: object, capsys: object) -> None:
        """cli_main() returns 1 when an input file does not exist."""
        monkeypatch.setattr("sys.argv", ["lint", "/nonexistent/file.yml"])  # type: ignore[attr-defined]
        result = cli_main(
            description="test",
            epilog="test",
            lint_fn=_noop_lint,
        )
        assert result == 1
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert "File not found" in captured.err

    def test_existing_file_returns_zero(self, monkeypatch: object, tmp_path: Path) -> None:
        """cli_main() returns 0 when all files exist and have no errors."""
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr("sys.argv", ["lint", str(compose_file)])  # type: ignore[attr-defined]
        result = cli_main(
            description="test",
            epilog="test",
            lint_fn=_noop_lint,
        )
        assert result == 0


class TestFormatResult:
    def test_with_service(self) -> None:
        result = LintResult(severity=Severity.ERROR, check_id="CHK1", service="app", message="bad")
        output = format_result(result)
        assert "[app]" in output
        assert "ERROR" in output

    def test_without_service(self) -> None:
        result = LintResult(severity=Severity.WARN, check_id="CHK2", service="", message="warn")
        output = format_result(result)
        assert "[CHK2]" in output
        assert "WARN" in output
        # No service bracket like [svc] in the location part
        assert output.count("[") == 1  # only the check_id bracket


class TestCliMainWithFindings:
    def test_returns_one_on_error_findings(self, monkeypatch: object, tmp_path: Path, capsys: object) -> None:
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr("sys.argv", ["lint", str(compose_file)])  # type: ignore[attr-defined]

        def lint_with_errors(_path: Path) -> list[LintResult]:
            return [LintResult(severity=Severity.ERROR, check_id="T1", service="svc", message="error")]

        result = cli_main(description="test", epilog="test", lint_fn=lint_with_errors)
        assert result == 1
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert "1 ERROR" in captured.out
        assert "Found:" in captured.out
