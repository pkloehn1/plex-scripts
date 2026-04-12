"""Tests for list_pr_review_comments_filtered module."""

from __future__ import annotations

import json

from scripts.github.gh_cli import GhCliError, GhResult
from scripts.github.list_pr_review_comments_filtered import _build_parser, _matches_filters, main

# -- _matches_filters ----------------------------------------------------------


def test_no_filters_matches_all() -> None:
    assert _matches_filters({"author": "x", "body": "y", "path": "z"}, author_substring=None, contains=None, path=None)


def test_author_match() -> None:
    assert _matches_filters({"author": "copilot-bot"}, author_substring="copilot", contains=None, path=None)


def test_author_no_match() -> None:
    assert not _matches_filters({"author": "alice"}, author_substring="copilot", contains=None, path=None)


def test_author_none_value() -> None:
    assert not _matches_filters({"author": None}, author_substring="copilot", contains=None, path=None)


def test_author_non_string() -> None:
    assert not _matches_filters({"author": 123}, author_substring="copilot", contains=None, path=None)


def test_contains_match() -> None:
    assert _matches_filters({"body": "Please fix this"}, author_substring=None, contains="fix", path=None)


def test_contains_no_match() -> None:
    assert not _matches_filters({"body": "looks good"}, author_substring=None, contains="fix", path=None)


def test_contains_none_body() -> None:
    assert not _matches_filters({"body": None}, author_substring=None, contains="fix", path=None)


def test_path_exact_match() -> None:
    assert _matches_filters({"path": "src/main.py"}, author_substring=None, contains=None, path="src/main.py")


def test_path_no_match() -> None:
    assert not _matches_filters({"path": "src/other.py"}, author_substring=None, contains=None, path="src/main.py")


def test_path_non_string() -> None:
    assert not _matches_filters({"path": None}, author_substring=None, contains=None, path="src/main.py")


def test_combined_filters() -> None:
    comment = {"author": "copilot-bot", "body": "Fix this issue", "path": "src/main.py"}
    assert _matches_filters(comment, author_substring="copilot", contains="fix", path="src/main.py")
    assert not _matches_filters(comment, author_substring="copilot", contains="refactor", path="src/main.py")


# -- _build_parser -------------------------------------------------------------


def test_build_parser() -> None:
    parser = _build_parser()
    args = parser.parse_args(["--repo", "o/n", "--pr", "42", "--author-substring", "copilot"])
    assert args.author_substring == "copilot"
    assert args.pr == 42


# -- main ----------------------------------------------------------------------


def test_main_success(monkeypatch, capsys) -> None:
    # Raw API format: author lives under user.login
    raw_comments = [
        {
            "id": 1,
            "node_id": "N1",
            "user": {"login": "copilot-bot"},
            "body": "fix",
            "path": "f.py",
            "line": 5,
            "html_url": "https://x",
        }
    ]

    class _FakeRunner:
        def run(self, argv, *, input_text=None):
            return GhResult(stdout=json.dumps(raw_comments), stderr="")

    monkeypatch.setattr("scripts.github.list_pr_review_comments_filtered.SubprocessGhRunner", _FakeRunner)
    monkeypatch.setattr("sys.argv", ["prog", "--repo", "o/n", "--pr", "42", "--author-substring", "copilot"])
    assert main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["count"] == 1


def test_main_gh_cli_error(monkeypatch) -> None:
    class _ErrorRunner:
        def run(self, argv, *, input_text=None):
            raise GhCliError("fail", argv=argv, returncode=1, stdout="", stderr="oops")

    monkeypatch.setattr("scripts.github.list_pr_review_comments_filtered.SubprocessGhRunner", _ErrorRunner)
    monkeypatch.setattr("sys.argv", ["prog", "--repo", "o/n", "--pr", "42"])
    assert main() == 2


def test_main_value_error(monkeypatch) -> None:
    class _BadRunner:
        def run(self, argv, *, input_text=None):
            return GhResult(stdout="{}", stderr="")

    monkeypatch.setattr("scripts.github.list_pr_review_comments_filtered.SubprocessGhRunner", _BadRunner)
    monkeypatch.setattr("sys.argv", ["prog", "--repo", "o/n", "--pr", "42"])
    assert main() == 2
