"""Tests for delete_branch module."""

from __future__ import annotations

import pytest

from scripts.github.conftest import ExpectedCall, QueueRunner
from scripts.github.delete_branch import _build_parser, _validate_branch, delete_branch

# -- _validate_branch ---------------------------------------------------------


def test_validate_branch_valid_simple() -> None:
    assert _validate_branch("main") == "main"


def test_validate_branch_valid_with_slashes() -> None:
    assert _validate_branch("feature/foo-bar") == "feature/foo-bar"


def test_validate_branch_strips_whitespace() -> None:
    assert _validate_branch("  my-branch  ") == "my-branch"


def test_validate_branch_valid_with_dots() -> None:
    assert _validate_branch("release/v1.2.3") == "release/v1.2.3"


@pytest.mark.parametrize(
    ("bad", "match"),
    [
        ("", "required"),
        ("   ", "required"),
        ("refs/heads/main", "not a full ref"),
        ("/leading-slash", "start/end"),
        ("trailing-slash/", "start/end"),
        ("double//slash", "start/end"),
        (".starts-with-dot", "invalid characters"),
    ],
)
def test_validate_branch_rejects_invalid(bad: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        _validate_branch(bad)


# -- delete_branch ------------------------------------------------------------

_REPO = "owner/name"
_BRANCH = "feature/cleanup"


def test_delete_branch_success() -> None:
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "--method",
                    "DELETE",
                    f"/repos/{_REPO}/git/refs/heads/{_BRANCH}",
                ],
                stdout="null",
            ),
        ]
    )
    result = delete_branch(runner=runner, repo=_REPO, branch=_BRANCH)
    assert result["ok"] is True
    assert result["repo"] == _REPO
    assert result["branch"] == _BRANCH
    assert result["stdout"] == "null"
    runner.assert_exhausted()


def test_delete_branch_rejects_invalid_branch() -> None:
    runner = QueueRunner([])
    with pytest.raises(ValueError, match="required"):
        delete_branch(runner=runner, repo=_REPO, branch="")


def test_delete_branch_rejects_full_ref() -> None:
    runner = QueueRunner([])
    with pytest.raises(ValueError, match="not a full ref"):
        delete_branch(runner=runner, repo=_REPO, branch="refs/heads/main")


# -- _build_parser ------------------------------------------------------------


def test_build_parser_returns_parser_with_expected_args() -> None:
    parser = _build_parser()
    parsed = parser.parse_args(
        [
            "--branch",
            "feature/foo",
            "--repo",
            "owner/name",
            "--json",
        ]
    )
    assert parsed.branch == "feature/foo"
    assert parsed.repo == "owner/name"
    assert parsed.json is True


def test_build_parser_defaults() -> None:
    parser = _build_parser()
    parsed = parser.parse_args(["--branch", "main"])
    assert parsed.repo is None
    assert parsed.json is False
