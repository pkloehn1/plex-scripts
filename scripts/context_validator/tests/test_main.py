"""Tests for main module."""

import argparse
import sys
from pathlib import Path
from unittest.mock import patch

from scripts.common.paths import repo_root
from scripts.context_validator.main import (
    _MULTI_AGENT_WORKSPACE,
    _load_run_config,
    _print_result,
    _print_summary,
    _RunTotals,
    _validate_files,
)
from scripts.context_validator.validator import ValidationResult

# The __init__.py re-exports 'main' as a function, so use sys.modules for the module.
_MAIN_MOD = "scripts.context_validator.main"
_REPO_ROOT = repo_root()


def _fake_result(base: Path | None = None, *, status: str = "ok", tokens: int = 25) -> ValidationResult:
    # Use repo root so _print_result's relative_to() works in main() tests.
    root = base if base is not None else _REPO_ROOT
    chars = {"ok": 100, "info": 20000, "warning": 28000, "error": 40000}
    return ValidationResult(
        path=str(root / "f.md"),
        char_count=chars.get(status, 100),
        token_count=tokens,
        token_limit=8000,
        provider="default",
        status=status,
    )


# ---------------------------------------------------------------------------
# _RunTotals
# ---------------------------------------------------------------------------


class TestRunTotals:
    def test_initial_state(self):
        totals = _RunTotals()
        assert totals.errors == 0
        assert totals.warnings == 0
        assert totals.overall_tokens == 0
        assert totals.overall_files == 0

    def test_record_ok(self):
        totals = _RunTotals()
        totals.current_section = "Test"
        result = _fake_result(Path("/tmp"))
        totals.record(result)
        assert totals.overall_tokens == 25
        assert totals.overall_files == 1
        assert totals.errors == 0
        assert totals.warnings == 0

    def test_record_error(self):
        totals = _RunTotals()
        totals.record(_fake_result(Path("/tmp"), status="error", tokens=10000))
        assert totals.errors == 1

    def test_record_warning(self):
        totals = _RunTotals()
        totals.record(_fake_result(Path("/tmp"), status="warning", tokens=7000))
        assert totals.warnings == 1

    def test_close_section_no_current(self, capsys):
        totals = _RunTotals()
        totals.close_section()
        assert capsys.readouterr().out == ""

    def test_close_section_updates_category_totals(self):
        totals = _RunTotals()
        totals.current_section = "Test"
        totals.section_tokens = 500
        totals.section_files = 1
        totals.close_section()
        assert totals.category_totals["Test"] == 500

    def test_close_section_prints_subtotal_for_multi_file(self, capsys):
        totals = _RunTotals()
        totals.current_section = "Test"
        totals.section_tokens = 500
        totals.section_files = 3
        totals.close_section()
        output = capsys.readouterr().out
        assert "500 tokens" in output
        assert "3 files" in output

    def test_open_section_switches(self, capsys):
        totals = _RunTotals()
        totals.open_section("First")
        assert totals.current_section == "First"
        assert totals.section_tokens == 0
        assert totals.section_files == 0
        output = capsys.readouterr().out
        assert "First:" in output

    def test_open_section_closes_previous(self):
        totals = _RunTotals()
        totals.open_section("First")
        totals.section_tokens = 100
        totals.section_files = 1
        totals.open_section("Second")
        assert totals.category_totals["First"] == 100
        assert totals.current_section == "Second"

    def test_close_section_accumulates(self):
        totals = _RunTotals()
        totals.current_section = "Test"
        totals.section_tokens = 100
        totals.section_files = 1
        totals.close_section()
        totals.current_section = "Test"
        totals.section_tokens = 200
        totals.section_files = 1
        totals.close_section()
        assert totals.category_totals["Test"] == 300


# ---------------------------------------------------------------------------
# _print_result
# ---------------------------------------------------------------------------


class TestPrintResult:
    def test_ok_result(self, capsys, tmp_path: Path):
        result = _fake_result(tmp_path)
        _print_result(result, tmp_path)
        output = capsys.readouterr().out
        assert "[OK]" in output
        assert "Default (Copilot)" in output

    def test_error_result(self, capsys, tmp_path: Path):
        result = _fake_result(tmp_path, status="error", tokens=10000)
        _print_result(result, tmp_path)
        assert "[ERR]" in capsys.readouterr().out

    def test_warning_result(self, capsys, tmp_path: Path):
        result = _fake_result(tmp_path, status="warning", tokens=7000)
        _print_result(result, tmp_path)
        assert "[WARN]" in capsys.readouterr().out

    def test_info_result(self, capsys, tmp_path: Path):
        result = _fake_result(tmp_path, status="info", tokens=5000)
        _print_result(result, tmp_path)
        assert "[INFO]" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    def _run_main(self, args, config, results):
        """Run main() with all external dependencies patched.

        Uses _REPO_ROOT for result paths so _print_result's relative_to() works
        with the repo_root computed from __file__ inside main().
        """
        result_iter = iter(results)

        def fake_find(root, pattern):
            try:
                res = next(result_iter)
                return [Path(res.path)]
            except StopIteration:
                return []

        def fake_validate(path, cpt, info, warn):
            for res in results:
                if Path(res.path) == path:
                    return res
            return results[0] if results else None

        main_mod = sys.modules[_MAIN_MOD]

        with (
            patch.object(main_mod, "parse_args", return_value=args),
            patch.object(main_mod, "load_config", return_value=config),
            patch.object(main_mod, "find_files", side_effect=fake_find),
            patch.object(main_mod, "validate_file", side_effect=fake_validate),
        ):
            return main_mod.main()

    def _default_config(self):
        return {"CHARS_PER_TOKEN": 4, "INFO_THRESHOLD_PERCENT": 50, "WARN_THRESHOLD_PERCENT": 75}

    def test_returns_zero_when_all_ok(self, capsys):
        args = argparse.Namespace(compare_to=None)
        result = self._run_main(args, self._default_config(), [_fake_result()])
        assert result == 0
        assert "SUCCESS" in capsys.readouterr().out

    def test_returns_one_on_error(self, capsys):
        args = argparse.Namespace(compare_to=None)
        result = self._run_main(args, self._default_config(), [_fake_result(status="error", tokens=10000)])
        assert result == 1
        assert "FAILED" in capsys.readouterr().out

    def test_warns_on_warning(self, capsys):
        args = argparse.Namespace(compare_to=None)
        result = self._run_main(args, self._default_config(), [_fake_result(status="warning", tokens=7000)])
        assert result == 0
        assert "WARNING" in capsys.readouterr().out

    def test_compare_to_mode(self, capsys):
        args = argparse.Namespace(compare_to="origin/main")
        result = self._run_main(args, self._default_config(), [])
        assert result == 0
        assert "origin/main" in capsys.readouterr().out

    def test_no_files_found(self):
        args = argparse.Namespace(compare_to=None)
        result = self._run_main(args, self._default_config(), [])
        assert result == 0

    def test_uses_config_defaults(self):
        args = argparse.Namespace(compare_to=None)
        result = self._run_main(args, {}, [])
        assert result == 0


# ---------------------------------------------------------------------------
# _MULTI_AGENT_WORKSPACE constant
# ---------------------------------------------------------------------------


class TestMultiAgentWorkspaceConstant:
    def test_constant_value(self):
        assert _MULTI_AGENT_WORKSPACE == "Multi-Agent Workspace"

    def test_used_in_file_checks(self):
        from scripts.context_validator.main import _FILE_CHECKS

        workspace_entries = [section for section, _ in _FILE_CHECKS if section == _MULTI_AGENT_WORKSPACE]
        assert len(workspace_entries) == 5


# ---------------------------------------------------------------------------
# _load_run_config
# ---------------------------------------------------------------------------


class TestLoadRunConfig:
    def test_returns_repo_root_and_config(self):
        main_mod = sys.modules[_MAIN_MOD]
        config = {"CHARS_PER_TOKEN": 4, "INFO_THRESHOLD_PERCENT": 50, "WARN_THRESHOLD_PERCENT": 75}
        with patch.object(main_mod, "load_config", return_value=config):
            root, cfg = _load_run_config()
        assert root.is_dir()
        assert cfg == {"chars_per_token": 4, "info_pct": 50, "warn_pct": 75}

    def test_uses_defaults_for_missing_keys(self):
        main_mod = sys.modules[_MAIN_MOD]
        with patch.object(main_mod, "load_config", return_value={}):
            _, cfg = _load_run_config()
        assert cfg == {"chars_per_token": 4, "info_pct": 50, "warn_pct": 75}


# ---------------------------------------------------------------------------
# _validate_files
# ---------------------------------------------------------------------------


class TestValidateFiles:
    def test_returns_totals(self):
        main_mod = sys.modules[_MAIN_MOD]
        result = _fake_result()

        with (
            patch.object(main_mod, "find_files", return_value=[Path(result.path)]),
            patch.object(main_mod, "validate_file", return_value=result),
        ):
            totals = _validate_files(_REPO_ROOT, {"chars_per_token": 4, "info_pct": 50, "warn_pct": 75})
        assert totals.overall_files > 0
        assert totals.overall_tokens > 0

    def test_no_files(self):
        main_mod = sys.modules[_MAIN_MOD]

        with patch.object(main_mod, "find_files", return_value=[]):
            totals = _validate_files(_REPO_ROOT, {"chars_per_token": 4, "info_pct": 50, "warn_pct": 75})
        assert totals.overall_files == 0


# ---------------------------------------------------------------------------
# _print_summary
# ---------------------------------------------------------------------------


class TestPrintSummary:
    def test_success(self, capsys):
        totals = _RunTotals(overall_tokens=100, overall_files=2)
        code = _print_summary(totals)
        assert code == 0
        assert "SUCCESS" in capsys.readouterr().out

    def test_error_returns_one(self, capsys):
        totals = _RunTotals(errors=1, overall_tokens=10000, overall_files=1)
        code = _print_summary(totals)
        assert code == 1
        assert "FAILED" in capsys.readouterr().out

    def test_warning_returns_zero(self, capsys):
        totals = _RunTotals(warnings=2, overall_tokens=7000, overall_files=2)
        code = _print_summary(totals)
        assert code == 0
        assert "WARNING" in capsys.readouterr().out
