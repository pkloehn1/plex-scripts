"""Tests for action_run_logs module."""

from __future__ import annotations

import json

import pytest

from scripts.github.action_run_logs import (
    _build_parser,
    _download_logs,
    _resolve_job_id,
    main,
)
from scripts.github.conftest import ExpectedCall, QueueRunner
from scripts.github.gh_cli import GhCliError, GhResult

_REPO = "owner/name"


def _jobs_argv(run_id: int) -> list[str]:
    return ["gh", "run", "view", str(run_id), "--repo", _REPO, "--json", "jobs"]


def _log_argv(run_id: int, job_id: int | None = None) -> list[str]:
    argv = ["gh", "run", "view", str(run_id), "--repo", _REPO, "--log"]
    if job_id is not None:
        argv.extend(["--job", str(job_id)])
    return argv


# -- _build_parser -------------------------------------------------------------


def test_build_parser() -> None:
    parser = _build_parser()
    assert parser is not None


# -- _resolve_job_id -----------------------------------------------------------


def test_resolve_none_when_no_job_name() -> None:
    runner = QueueRunner([])
    assert _resolve_job_id(runner=runner, repo=_REPO, run_id=1, job_name=None) is None


def test_resolve_matching_job() -> None:
    payload = {"jobs": [{"name": "lint", "databaseId": 10}, {"name": "test", "databaseId": 20}]}
    runner = QueueRunner([ExpectedCall(argv=_jobs_argv(1), stdout=json.dumps(payload))])
    assert _resolve_job_id(runner=runner, repo=_REPO, run_id=1, job_name="test") == 20
    runner.assert_exhausted()


def test_resolve_case_insensitive() -> None:
    payload = {"jobs": [{"name": "Pre-Commit", "databaseId": 30}]}
    runner = QueueRunner([ExpectedCall(argv=_jobs_argv(1), stdout=json.dumps(payload))])
    assert _resolve_job_id(runner=runner, repo=_REPO, run_id=1, job_name="pre-commit") == 30


def test_resolve_raises_on_non_dict_payload() -> None:
    runner = QueueRunner([ExpectedCall(argv=_jobs_argv(1), stdout="[1,2]")])
    with pytest.raises(ValueError, match="Unexpected gh run view payload"):
        _resolve_job_id(runner=runner, repo=_REPO, run_id=1, job_name="x")


def test_resolve_raises_on_non_list_jobs() -> None:
    runner = QueueRunner([ExpectedCall(argv=_jobs_argv(1), stdout='{"jobs": "bad"}')])
    with pytest.raises(ValueError, match="Missing jobs payload"):
        _resolve_job_id(runner=runner, repo=_REPO, run_id=1, job_name="x")


def test_resolve_raises_on_no_match() -> None:
    payload = {"jobs": [{"name": "lint", "databaseId": 10}]}
    runner = QueueRunner([ExpectedCall(argv=_jobs_argv(1), stdout=json.dumps(payload))])
    with pytest.raises(ValueError, match="Job name not found"):
        _resolve_job_id(runner=runner, repo=_REPO, run_id=1, job_name="deploy")


def test_resolve_raises_on_ambiguous() -> None:
    payload = {"jobs": [{"name": "test-a", "databaseId": 1}, {"name": "test-b", "databaseId": 2}]}
    runner = QueueRunner([ExpectedCall(argv=_jobs_argv(1), stdout=json.dumps(payload))])
    with pytest.raises(ValueError, match="ambiguous"):
        _resolve_job_id(runner=runner, repo=_REPO, run_id=1, job_name="test")


def test_resolve_raises_on_missing_database_id() -> None:
    payload = {"jobs": [{"name": "lint"}]}
    runner = QueueRunner([ExpectedCall(argv=_jobs_argv(1), stdout=json.dumps(payload))])
    with pytest.raises(ValueError, match="Missing job databaseId"):
        _resolve_job_id(runner=runner, repo=_REPO, run_id=1, job_name="lint")


def test_resolve_raises_on_zero_database_id() -> None:
    payload = {"jobs": [{"name": "lint", "databaseId": 0}]}
    runner = QueueRunner([ExpectedCall(argv=_jobs_argv(1), stdout=json.dumps(payload))])
    with pytest.raises(ValueError, match="Missing job databaseId"):
        _resolve_job_id(runner=runner, repo=_REPO, run_id=1, job_name="lint")


def test_resolve_skips_non_dict_jobs() -> None:
    payload = {"jobs": ["skip", {"name": "lint", "databaseId": 10}]}
    runner = QueueRunner([ExpectedCall(argv=_jobs_argv(1), stdout=json.dumps(payload))])
    assert _resolve_job_id(runner=runner, repo=_REPO, run_id=1, job_name="lint") == 10


def test_resolve_skips_non_string_name() -> None:
    payload = {"jobs": [{"name": 123, "databaseId": 5}, {"name": "lint", "databaseId": 10}]}
    runner = QueueRunner([ExpectedCall(argv=_jobs_argv(1), stdout=json.dumps(payload))])
    assert _resolve_job_id(runner=runner, repo=_REPO, run_id=1, job_name="lint") == 10


# -- _download_logs ------------------------------------------------------------


def test_download_without_job_name() -> None:
    runner = QueueRunner([ExpectedCall(argv=_log_argv(100), stdout="log text")])
    logs = _download_logs(runner=runner, repo=_REPO, run_id=100, job_name=None)
    assert logs == [{"path": "all-jobs", "content": "log text"}]
    runner.assert_exhausted()


def test_download_with_job_name() -> None:
    jobs = {"jobs": [{"name": "lint", "databaseId": 42}]}
    runner = QueueRunner(
        [
            ExpectedCall(argv=_jobs_argv(100), stdout=json.dumps(jobs)),
            ExpectedCall(argv=_log_argv(100, 42), stdout="job log"),
        ]
    )
    logs = _download_logs(runner=runner, repo=_REPO, run_id=100, job_name="lint")
    assert logs == [{"path": "lint", "content": "job log"}]
    runner.assert_exhausted()


# -- main ----------------------------------------------------------------------


def test_main_success(monkeypatch, capsys) -> None:
    class _FakeRunner:
        def run(self, argv, *, input_text=None):
            return GhResult(stdout="log content", stderr="")

    monkeypatch.setattr("scripts.github.action_run_logs.SubprocessGhRunner", _FakeRunner)
    monkeypatch.setattr("sys.argv", ["prog", "--repo", _REPO, "--run-id", "100"])
    assert main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True
    assert output["repo"] == _REPO


def test_main_value_error(monkeypatch) -> None:
    class _FakeRunner:
        def run(self, argv, *, input_text=None):
            return GhResult(stdout='{"jobs": "bad"}', stderr="")

    monkeypatch.setattr("scripts.github.action_run_logs.SubprocessGhRunner", _FakeRunner)
    monkeypatch.setattr("sys.argv", ["prog", "--repo", _REPO, "--run-id", "1", "--job-name", "x"])
    assert main() == 2


def test_main_gh_cli_error(monkeypatch) -> None:
    class _ErrorRunner:
        def run(self, argv, *, input_text=None):
            raise GhCliError("fail", argv=argv, returncode=1, stdout="", stderr="oops")

    monkeypatch.setattr("scripts.github.action_run_logs.SubprocessGhRunner", _ErrorRunner)
    monkeypatch.setattr("sys.argv", ["prog", "--repo", _REPO, "--run-id", "1"])
    assert main() == 2


def test_main_auto_detects_repo(monkeypatch, capsys) -> None:
    call_count = 0

    class _FakeRunner:
        def run(self, argv, *, input_text=None):
            nonlocal call_count
            call_count += 1
            if "repo" in argv and "view" in argv:
                return GhResult(stdout=json.dumps({"nameWithOwner": "auto/repo"}), stderr="")
            return GhResult(stdout="logs", stderr="")

    monkeypatch.setattr("scripts.github.action_run_logs.SubprocessGhRunner", _FakeRunner)
    monkeypatch.setenv("GITHUB_REPOSITORY", "")
    monkeypatch.setattr("sys.argv", ["prog", "--run-id", "1"])
    assert main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["repo"] == "auto/repo"
