from __future__ import annotations

import scripts.testing.hooks.check_workflow_install_patterns as mod
from scripts.common.paths import repo_root
from scripts.testing.hooks.conftest import (
    assert_read_file_error,
    fake_file_reader,
    fake_staged_paths,
)

_WORKFLOW_PATH = ".github/workflows/a.yml"
_FIXTURES = repo_root() / "scripts" / "testing" / "hooks" / "fixtures" / "workflows"


def _load_fixture(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


def _patch_workflow(monkeypatch, workflow: str) -> None:
    """Stub staged-workflows to return a single workflow with the given content."""
    monkeypatch.setattr(mod, "_get_staged_workflows", lambda: fake_staged_paths([_WORKFLOW_PATH]))
    monkeypatch.setattr(mod, "_read_staged_file", fake_file_reader({_WORKFLOW_PATH: workflow}))


def test_requires_checkout(monkeypatch, capsys):
    _patch_workflow(monkeypatch, _load_fixture("no-checkout.yml"))

    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "missing actions/checkout" in err


def test_blocks_curl_bash(monkeypatch, capsys):
    _patch_workflow(monkeypatch, _load_fixture("curl-bash.yml"))

    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "curl|bash" in err


def test_blocks_curl_bash_no_space(monkeypatch, capsys):
    _patch_workflow(monkeypatch, _load_fixture("curl-bash-no-space.yml"))

    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "curl|bash" in err


def test_blocks_curl_bash_with_intermediate_command(monkeypatch, capsys):
    _patch_workflow(monkeypatch, _load_fixture("curl-sudo-bash.yml"))

    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "curl|bash" in err


def test_allows_good_workflow(monkeypatch):
    _patch_workflow(monkeypatch, _load_fixture("good-workflow.yml"))

    assert mod.main() == 0


def test_allows_api_only_job_without_checkout(monkeypatch):
    _patch_workflow(monkeypatch, _load_fixture("api-only-no-checkout.yml"))

    assert mod.main() == 0


def test_get_staged_workflows_git_error(monkeypatch, capsys):
    """_get_staged_workflows() returns error when git diff fails."""
    monkeypatch.setattr(mod, "_get_staged_workflows", lambda: ([], ["git diff --cached failed: git error"]))
    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "git diff --cached failed" in err


def test_read_staged_file_git_error(monkeypatch, capsys):
    """_read_staged_file() returns error when git show fails."""
    assert_read_file_error(mod, monkeypatch, capsys, "_get_staged_workflows", [_WORKFLOW_PATH])


def test_read_staged_file_returns_none_content(monkeypatch, capsys):
    """main() handles None content from _read_staged_file."""
    monkeypatch.setattr(mod, "_get_staged_workflows", lambda: fake_staged_paths([_WORKFLOW_PATH]))

    def fake_reader_none(path):
        return None, None

    monkeypatch.setattr(mod, "_read_staged_file", fake_reader_none)
    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "Unable to read staged file content" in err


def test_yaml_parse_error(monkeypatch, capsys):
    """Parse error is reported."""
    _patch_workflow(monkeypatch, "jobs:\n  test:\n    steps: [\n      - bad")

    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "YAML parse error" in err


def test_jobs_not_dict_skipped(monkeypatch):
    """Workflow with jobs: null is skipped."""
    _patch_workflow(monkeypatch, _load_fixture("jobs-null.yml"))

    assert mod.main() == 0


def test_job_not_dict_skipped(monkeypatch):
    """Job value that's not a dict is skipped."""
    _patch_workflow(monkeypatch, _load_fixture("job-not-dict.yml"))

    assert mod.main() == 0


def test_segment_contains_shell_mid_token(monkeypatch, capsys):
    """Shell token detected mid-segment with whitespace."""
    _patch_workflow(monkeypatch, _load_fixture("curl-bash-mid-token.yml"))

    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "curl|bash" in err


def test_segment_contains_shell_after_special_char(monkeypatch, capsys):
    """Shell token detected after special character."""
    _patch_workflow(monkeypatch, _load_fixture("wget-bash-special-char.yml"))

    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "curl|bash" in err  # Error message is generic for both curl and wget


def test_get_staged_workflows_filters_non_yaml(monkeypatch):
    """_get_staged_workflows() filters out non-YAML files."""
    from pathlib import Path

    from scripts.common.git_runner import GitResult
    from scripts.testing.hooks import git_utils

    monkeypatch.setattr(
        git_utils,
        "run_git",
        lambda _args: GitResult(
            returncode=0,
            stdout=".github/workflows/ci.yml\n.github/workflows/notes.md\n.github/workflows/deploy.yaml\n",
            stderr="",
        ),
    )
    paths, errors = mod._get_staged_workflows()
    assert errors == []
    assert paths == [Path(".github/workflows/ci.yml"), Path(".github/workflows/deploy.yaml")]
