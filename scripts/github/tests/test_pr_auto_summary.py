"""Tests for pr_auto_summary module."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from scripts.common.git_runner import GitResult
from scripts.github.gh_cli import CliOperationError
from scripts.github.pr_auto_summary import (
    ParsedCommit,
    build_pr_body,
    detect_base_branch,
    format_summary_section,
    generate_auto_summary,
    get_branch_commits,
    group_commits_by_category,
    main,
    parse_commit_line,
    parse_git_log_output,
    refresh_auto_summary_in_body,
    replace_auto_summary_blocks,
)


class FakeGitRunner:
    """Test double for ``GitRunner`` protocol."""

    def __init__(self, results: list[GitResult]) -> None:
        self._results = list(results)
        self._index = 0

    def run_git(self, args: list[str], *, cwd: Path | None = None) -> GitResult:
        result = self._results[self._index]
        self._index += 1
        return result


# -- parse_commit_line ---------------------------------------------------------


def test_parse_commit_line_conventional() -> None:
    result = parse_commit_line("abc1234 feat(auth): add login")
    assert result is not None
    assert result.sha == "abc1234"
    assert result.type == "feat"
    assert result.scope == "auth"
    assert result.summary == "add login"
    assert result.is_dependabot is False


def test_parse_commit_line_no_scope() -> None:
    result = parse_commit_line("abc1234 fix: broken test")
    assert result is not None
    assert result.type == "fix"
    assert result.scope is None
    assert result.summary == "broken test"


def test_parse_commit_line_non_conventional() -> None:
    result = parse_commit_line("abc1234 random commit message")
    assert result is not None
    assert result.type is None
    assert result.scope is None


def test_parse_commit_line_dependabot() -> None:
    result = parse_commit_line("abc1234 Bump the dependencies group with 3 updates")
    assert result is not None
    assert result.is_dependabot is True


def test_parse_commit_line_empty() -> None:
    assert parse_commit_line("") is None
    assert parse_commit_line("   ") is None


def test_parse_commit_line_sha_only() -> None:
    assert parse_commit_line("abc1234") is None


# -- parse_git_log_output -----------------------------------------------------


def test_parse_git_log_output_multi_line() -> None:
    raw = "abc feat: one\ndef fix: two\n\nghi docs: three\n"
    commits = parse_git_log_output(raw)
    assert len(commits) == 3
    assert commits[0].type == "feat"
    assert commits[2].type == "docs"


# -- group_commits_by_category -------------------------------------------------


def test_group_commits_by_category_orders_correctly() -> None:
    commits = [
        ParsedCommit(sha="a", type="fix", scope=None, summary="fix", is_dependabot=False),
        ParsedCommit(sha="b", type="feat", scope=None, summary="feat", is_dependabot=False),
        ParsedCommit(sha="c", type=None, scope=None, summary="misc", is_dependabot=True),
    ]
    grouped = group_commits_by_category(commits)
    categories = list(grouped.keys())
    assert categories.index("\U0001f680 Features") < categories.index("\U0001f41b Bug Fixes")
    assert "\U0001f4e6 Dependencies" in categories


def test_group_commits_by_category_unknown_type() -> None:
    commits = [
        ParsedCommit(sha="a", type="unknown", scope=None, summary="x", is_dependabot=False),
    ]
    grouped = group_commits_by_category(commits)
    assert "Other" in grouped


# -- format_summary_section ----------------------------------------------------


def test_format_summary_section_empty() -> None:
    assert format_summary_section({}) == ""


def test_format_summary_section_with_scope() -> None:
    grouped = {
        "\U0001f680 Features": [
            ParsedCommit(sha="a", type="feat", scope="auth", summary="login", is_dependabot=False),
        ],
    }
    text = format_summary_section(grouped)
    assert "### \U0001f680 Features" in text
    assert "_(auth)_" in text
    assert "login" in text
    assert "(a)" in text


def test_format_summary_section_without_scope() -> None:
    grouped = {
        "\U0001f41b Bug Fixes": [
            ParsedCommit(sha="b", type="fix", scope=None, summary="crash", is_dependabot=False),
        ],
    }
    text = format_summary_section(grouped)
    assert "- crash (b)" in text


# -- build_pr_body ------------------------------------------------------------


def test_build_pr_body_with_issues() -> None:
    body = build_pr_body(summary_md="summary here", issue_numbers=[1, 2])
    assert "## Summary" in body
    assert "summary here" in body
    assert "Closes #1" in body
    assert "Closes #2" in body
    assert "auto-summary:start" in body


def test_build_pr_body_no_issues() -> None:
    body = build_pr_body(summary_md="summary", issue_numbers=None)
    assert "Closes #ISSUE_NUMBER" in body


# -- replace_auto_summary_blocks -----------------------------------------------


def test_replace_auto_summary_blocks_replaces() -> None:
    existing = (
        "## Summary\n\n"
        "<!-- auto-summary:start -->\nold content\n<!-- auto-summary:end -->\n\n"
        "## Other\n\nmanual content\n"
    )
    result = replace_auto_summary_blocks(existing, "new content")
    assert "new content" in result
    assert "old content" not in result
    assert "manual content" in result


def test_replace_auto_summary_blocks_no_markers() -> None:
    existing = "no markers here"
    assert replace_auto_summary_blocks(existing, "new") == existing


# -- generate_auto_summary -----------------------------------------------------


def test_generate_auto_summary_no_commits() -> None:
    summary = generate_auto_summary([])
    assert summary.commit_count == 0
    assert "No commits found" in summary.summary_md
    assert "## Summary" in summary.full_body


def test_generate_auto_summary_with_commits() -> None:
    commits = [
        ParsedCommit(sha="a", type="feat", scope=None, summary="add x", is_dependabot=False),
        ParsedCommit(sha="b", type="fix", scope="core", summary="fix y", is_dependabot=False),
    ]
    summary = generate_auto_summary(commits, issue_numbers=[42])
    assert summary.commit_count == 2
    assert "### \U0001f680 Features" in summary.summary_md
    assert "### \U0001f41b Bug Fixes" in summary.summary_md
    assert "Closes #42" in summary.full_body


# -- group_commits_by_category: type=None, not dependabot -> "Other" (line 149) --


def test_group_commits_non_conventional_non_dependabot_falls_to_other() -> None:
    non_conventional_commit = ParsedCommit(
        sha="abc",
        type=None,
        scope=None,
        summary="random message",
        is_dependabot=False,
    )
    grouped = group_commits_by_category([non_conventional_commit])
    assert "Other" in grouped
    assert len(grouped["Other"]) == 1
    assert grouped["Other"][0].sha == "abc"


# -- get_branch_commits: git log fails -> CliOperationError (line 314) ---------


def test_get_branch_commits_raises_on_failure() -> None:
    failed_result = GitResult(returncode=1, stdout="", stderr="fatal: bad revision")
    fake_runner = FakeGitRunner(results=[failed_result])
    with pytest.raises(CliOperationError, match="git log failed"):
        get_branch_commits(runner=fake_runner, base_branch="main")


def test_get_branch_commits_success() -> None:
    log_output = "abc1234 feat: add login\ndef5678 fix: crash\n"
    success_result = GitResult(returncode=0, stdout=log_output, stderr="")
    fake_runner = FakeGitRunner(results=[success_result])
    commits = get_branch_commits(runner=fake_runner, base_branch="main")
    assert len(commits) == 2
    assert commits[0].type == "feat"
    assert commits[1].type == "fix"


# -- detect_base_branch: neither main nor master (lines 324-328) ---------------


def test_detect_base_branch_prefers_main() -> None:
    main_found = GitResult(returncode=0, stdout="abc123\n", stderr="")
    fake_runner = FakeGitRunner(results=[main_found])
    assert detect_base_branch(runner=fake_runner) == "main"


def test_detect_base_branch_falls_back_to_master() -> None:
    main_not_found = GitResult(returncode=1, stdout="", stderr="not found")
    master_found = GitResult(returncode=0, stdout="def456\n", stderr="")
    fake_runner = FakeGitRunner(results=[main_not_found, master_found])
    assert detect_base_branch(runner=fake_runner) == "master"


def test_detect_base_branch_raises_when_neither_exists() -> None:
    main_not_found = GitResult(returncode=1, stdout="", stderr="not found")
    master_not_found = GitResult(returncode=1, stdout="", stderr="not found")
    fake_runner = FakeGitRunner(results=[main_not_found, master_not_found])
    with pytest.raises(CliOperationError, match="neither 'main' nor 'master'"):
        detect_base_branch(runner=fake_runner)


# -- refresh_auto_summary_in_body ----------------------------------------------


def test_refresh_auto_summary_in_body_replaces_markers() -> None:
    existing_body = "## Summary\n\n<!-- auto-summary:start -->\nold content\n<!-- auto-summary:end -->\n\n## Other\n"
    log_output = "abc1234 feat(auth): add login\n"
    main_found = GitResult(returncode=0, stdout="abc123\n", stderr="")
    log_success = GitResult(returncode=0, stdout=log_output, stderr="")
    fake_runner = FakeGitRunner(results=[main_found, log_success])
    updated = refresh_auto_summary_in_body(existing_body=existing_body, git_runner=fake_runner)
    assert "old content" not in updated
    assert "add login" in updated
    assert "## Other" in updated


def test_refresh_auto_summary_in_body_no_markers_returns_unchanged() -> None:
    existing_body = "no markers here"
    fake_runner = FakeGitRunner(results=[])
    result = refresh_auto_summary_in_body(existing_body=existing_body, git_runner=fake_runner)
    assert result == existing_body


def test_refresh_auto_summary_in_body_empty_returns_unchanged() -> None:
    fake_runner = FakeGitRunner(results=[])
    assert refresh_auto_summary_in_body(existing_body="", git_runner=fake_runner) == ""


# -- main() CLI entry point (lines 338-381) ------------------------------------


def test_main_json_output(monkeypatch, capsys) -> None:
    """Exercise main() end-to-end including _DefaultGitRunner.run_git delegation."""
    fake_git_result = GitResult(returncode=0, stdout="a1b2c3 feat(core): add feature\n", stderr="")
    monkeypatch.setattr(
        "scripts.common.git_runner.run_git",
        lambda git_args, cwd=None: fake_git_result,
    )
    monkeypatch.setattr(sys, "argv", ["prog", "--base", "main", "--json"])

    exit_code = main()
    assert exit_code == 0

    output = json.loads(capsys.readouterr().out)
    assert output["commit_count"] == 1
    assert "add feature" in output["summary_md"]
    assert "## Summary" in output["full_body"]


def test_main_plain_output(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "scripts.github.pr_auto_summary.detect_base_branch",
        lambda **kwargs: "main",
    )
    monkeypatch.setattr(
        "scripts.github.pr_auto_summary.get_branch_commits",
        lambda **kwargs: [
            ParsedCommit(sha="d4e5f6", type="fix", scope=None, summary="fix crash", is_dependabot=False),
        ],
    )
    monkeypatch.setattr(sys, "argv", ["prog"])

    exit_code = main()
    assert exit_code == 0

    output_text = capsys.readouterr().out
    assert "## Summary" in output_text
    assert "fix crash" in output_text


def test_main_with_base_and_issue(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "scripts.github.pr_auto_summary.get_branch_commits",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(sys, "argv", ["prog", "--base", "develop", "--issue", "42", "--json"])

    exit_code = main()
    assert exit_code == 0

    output = json.loads(capsys.readouterr().out)
    assert output["commit_count"] == 0
    assert "Closes #42" in output["full_body"]


def test_main_output_to_file(monkeypatch, tmp_path) -> None:
    output_file = tmp_path / "pr_body.md"
    monkeypatch.setattr(
        "scripts.github.pr_auto_summary.detect_base_branch",
        lambda **kwargs: "main",
    )
    monkeypatch.setattr(
        "scripts.github.pr_auto_summary.get_branch_commits",
        lambda **kwargs: [
            ParsedCommit(sha="abc123", type="docs", scope=None, summary="update readme", is_dependabot=False),
        ],
    )
    monkeypatch.setattr(sys, "argv", ["prog", "--output", str(output_file)])

    exit_code = main()
    assert exit_code == 0
    assert output_file.exists()

    written_content = output_file.read_text(encoding="utf-8")
    assert "## Summary" in written_content
    assert "update readme" in written_content
