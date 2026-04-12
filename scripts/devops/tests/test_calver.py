"""TDD contract tests for CalVer versioning module."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.common.git_runner import GitResult
from scripts.devops.calver import (
    CalVerResult,
    _DefaultGitRunner,
    compute_next_version,
    list_tags,
    main,
    parse_calver_tag,
)

# ---------------------------------------------------------------------------
# Stub GitRunner (follows _StubGhRunner pattern from scripts/github/conftest.py)
# ---------------------------------------------------------------------------


class _StubGitRunner:
    """Stub implementing GitRunner Protocol for deterministic tests."""

    def __init__(self, tag_output: str = "", returncode: int = 0) -> None:
        self.tag_output = tag_output
        self.returncode = returncode

    def run_git(self, args: list[str], *, cwd: Path | None = None) -> GitResult:
        return GitResult(returncode=self.returncode, stdout=self.tag_output, stderr="")


# ---------------------------------------------------------------------------
# CalVerResult dataclass
# ---------------------------------------------------------------------------


class TestCalVerResult:
    def test_frozen(self) -> None:
        result = CalVerResult(version="2026.03.0", tag="v2026.03.0", year=2026, month=3, micro=0)
        with pytest.raises(AttributeError):
            result.version = "other"  # type: ignore[misc]

    def test_iter_unpacking(self) -> None:
        result = CalVerResult(version="2026.03.0", tag="v2026.03.0", year=2026, month=3, micro=0)
        version, tag, year, month, micro = result
        assert version == "2026.03.0"
        assert tag == "v2026.03.0"
        assert year == 2026
        assert month == 3
        assert micro == 0


# ---------------------------------------------------------------------------
# parse_calver_tag
# ---------------------------------------------------------------------------


class TestParseCalverTag:
    def test_valid_tag(self) -> None:
        result = parse_calver_tag("v2026.03.0")
        assert result is not None
        assert result.version == "2026.03.0"
        assert result.tag == "v2026.03.0"
        assert result.year == 2026
        assert result.month == 3
        assert result.micro == 0

    def test_valid_tag_high_micro(self) -> None:
        result = parse_calver_tag("v2026.03.42")
        assert result is not None
        assert result.micro == 42

    def test_missing_v_prefix(self) -> None:
        assert parse_calver_tag("2026.03.0") is None

    def test_non_zero_padded_month(self) -> None:
        assert parse_calver_tag("v2026.3.0") is None

    def test_invalid_month_zero(self) -> None:
        assert parse_calver_tag("v2026.00.0") is None

    def test_invalid_month_thirteen(self) -> None:
        assert parse_calver_tag("v2026.13.0") is None

    def test_malformed_string(self) -> None:
        assert parse_calver_tag("not-a-tag") is None

    def test_empty_string(self) -> None:
        assert parse_calver_tag("") is None

    def test_semver_tag_rejected(self) -> None:
        assert parse_calver_tag("v1.2.3") is None


# ---------------------------------------------------------------------------
# compute_next_version
# ---------------------------------------------------------------------------


class TestComputeNextVersion:
    def test_no_existing_tags(self) -> None:
        now = datetime(2026, 3, 1, tzinfo=UTC)
        result = compute_next_version([], now)
        assert result.version == "2026.03.0"
        assert result.tag == "v2026.03.0"
        assert result.year == 2026
        assert result.month == 3
        assert result.micro == 0

    def test_single_tag_same_month(self) -> None:
        now = datetime(2026, 3, 15, tzinfo=UTC)
        result = compute_next_version(["v2026.03.0"], now)
        assert result.version == "2026.03.1"
        assert result.micro == 1

    def test_multiple_tags_same_month(self) -> None:
        now = datetime(2026, 3, 20, tzinfo=UTC)
        tags = ["v2026.03.0", "v2026.03.1", "v2026.03.2"]
        result = compute_next_version(tags, now)
        assert result.version == "2026.03.3"
        assert result.micro == 3

    def test_month_rollover_resets_micro(self) -> None:
        now = datetime(2026, 4, 1, tzinfo=UTC)
        tags = ["v2026.03.0", "v2026.03.1", "v2026.03.5"]
        result = compute_next_version(tags, now)
        assert result.version == "2026.04.0"
        assert result.micro == 0

    def test_year_rollover_resets_micro(self) -> None:
        now = datetime(2027, 1, 1, tzinfo=UTC)
        tags = ["v2026.12.3"]
        result = compute_next_version(tags, now)
        assert result.version == "2027.01.0"
        assert result.micro == 0

    def test_ignores_invalid_tags(self) -> None:
        now = datetime(2026, 3, 1, tzinfo=UTC)
        tags = ["v2026.03.0", "not-a-tag", "v1.2.3"]
        result = compute_next_version(tags, now)
        assert result.version == "2026.03.1"

    def test_ignores_different_month_tags(self) -> None:
        now = datetime(2026, 3, 1, tzinfo=UTC)
        tags = ["v2026.02.5", "v2026.03.0"]
        result = compute_next_version(tags, now)
        assert result.version == "2026.03.1"


# ---------------------------------------------------------------------------
# list_tags
# ---------------------------------------------------------------------------


class TestListTags:
    def test_success(self) -> None:
        runner = _StubGitRunner(tag_output="v2026.03.0\nv2026.03.1\n")
        tags = list_tags(runner)
        assert tags == ["v2026.03.0", "v2026.03.1"]

    def test_empty_repo(self) -> None:
        runner = _StubGitRunner(tag_output="")
        tags = list_tags(runner)
        assert tags == []

    def test_git_failure_returns_empty(self) -> None:
        runner = _StubGitRunner(returncode=128)
        tags = list_tags(runner)
        assert tags == []

    def test_default_runner_delegates_to_run_git(self) -> None:
        runner = _DefaultGitRunner()
        result = runner.run_git(["--version"])
        assert result.returncode == 0
        assert "git version" in result.stdout


# ---------------------------------------------------------------------------
# CLI main
# ---------------------------------------------------------------------------


class TestMain:
    _FIXED_NOW = datetime(2026, 3, 15, tzinfo=UTC)
    _STUB_RUNNER = _StubGitRunner(tag_output="v2026.03.0\nv2026.03.1\n")

    def test_dry_run(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = main(["--dry-run"], runner=self._STUB_RUNNER, now=self._FIXED_NOW)
        captured = capsys.readouterr()
        assert code == 0
        assert captured.out.strip() == "2026.03.2"

    def test_default_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = main([], runner=self._STUB_RUNNER, now=self._FIXED_NOW)
        captured = capsys.readouterr()
        assert code == 0
        lines = captured.out.strip().splitlines()
        assert "version=2026.03.2" in lines
        assert "tag=v2026.03.2" in lines
