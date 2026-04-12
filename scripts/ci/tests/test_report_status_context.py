"""Tests for scripts.ci.report_status_context."""

from __future__ import annotations

import pytest

import scripts.ci.report_status_context as mod
from scripts.github.gh_cli import GhCliError, GhResult


@pytest.fixture()
def _full_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("PR_NUMBER", "42")
    monkeypatch.setenv("JOB_STATUS", "success")
    monkeypatch.setenv("STATUS_CONTEXT", "ci/lint")
    monkeypatch.setenv("TARGET_URL", "https://example.com/run/1")
    monkeypatch.setenv("GH_TOKEN", "ghp_fake")


class TestMapJobStatus:
    def test_success(self) -> None:
        assert mod._map_job_status("success") == "success"

    def test_failure(self) -> None:
        assert mod._map_job_status("failure") == "failure"

    def test_cancelled(self) -> None:
        assert mod._map_job_status("cancelled") == "error"

    def test_unknown(self) -> None:
        assert mod._map_job_status("skipped") == "error"


class TestValidateEnv:
    def test_all_present(self, _full_env: None) -> None:
        env = mod._validate_env()
        assert env["GITHUB_REPOSITORY"] == "owner/repo"
        assert env["PR_NUMBER"] == "42"

    def test_missing_var_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.delenv("PR_NUMBER", raising=False)
        monkeypatch.delenv("JOB_STATUS", raising=False)
        monkeypatch.delenv("STATUS_CONTEXT", raising=False)
        monkeypatch.delenv("TARGET_URL", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        with pytest.raises(SystemExit, match="2"):
            mod._validate_env()


class TestFetchPrSha:
    def test_returns_sha(self) -> None:
        runner = _make_runner(stdout="abc123\n")
        assert mod._fetch_pr_sha("owner/repo", "42", runner=runner) == "abc123"

    def test_null_sha_raises(self) -> None:
        runner = _make_runner(stdout="null\n")
        with pytest.raises(SystemExit, match="2"):
            mod._fetch_pr_sha("owner/repo", "42", runner=runner)

    def test_empty_sha_raises(self) -> None:
        runner = _make_runner(stdout="\n")
        with pytest.raises(SystemExit, match="2"):
            mod._fetch_pr_sha("owner/repo", "42", runner=runner)

    def test_gh_error_raises(self) -> None:
        runner = _make_error_runner()
        with pytest.raises(GhCliError):
            mod._fetch_pr_sha("owner/repo", "42", runner=runner)


class TestPostStatus:
    def test_posts_correctly(self) -> None:
        runner = _make_runner(stdout="")
        mod._post_status(
            repo="owner/repo",
            sha="abc123",
            state="success",
            context="ci/lint",
            description="Reported by GitHub Actions (success)",
            target_url="https://example.com/run/1",
            runner=runner,
        )


class TestMain:
    @pytest.mark.usefixtures("_full_env")
    def test_success_end_to_end(self, monkeypatch: pytest.MonkeyPatch) -> None:
        runner = _make_runner(stdout="abc123\n")
        monkeypatch.setattr(mod, "_default_runner", lambda: runner)
        assert mod.main() == 0

    @pytest.mark.usefixtures("_full_env")
    def test_failure_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JOB_STATUS", "failure")
        runner = _make_runner(stdout="abc123\n")
        monkeypatch.setattr(mod, "_default_runner", lambda: runner)
        assert mod.main() == 0


# -- Test helpers --


class _StubRunner:
    def __init__(self, stdout: str = "", stderr: str = "") -> None:
        self._stdout = stdout
        self._stderr = stderr

    def run(self, argv: list[str], *, input_text: str | None = None) -> GhResult:
        return GhResult(stdout=self._stdout, stderr=self._stderr)


class _ErrorRunner:
    def run(self, argv: list[str], *, input_text: str | None = None) -> GhResult:
        raise GhCliError(
            "gh command failed",
            argv=argv,
            returncode=1,
            stdout="",
            stderr="not found",
        )


def _make_runner(stdout: str = "") -> _StubRunner:
    return _StubRunner(stdout=stdout)


def _make_error_runner() -> _ErrorRunner:
    return _ErrorRunner()
