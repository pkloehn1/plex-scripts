"""Tests for create_tag module."""

from __future__ import annotations

import json

import pytest

from scripts.github.conftest import ExpectedCall, QueueRunner
from scripts.github.create_tag import _build_parser, _validate_sha, _validate_tag, create_tag

# -- _validate_tag ------------------------------------------------------------


def test_validate_tag_valid_calver() -> None:
    assert _validate_tag("v2026.03.0") == "v2026.03.0"


def test_validate_tag_strips_whitespace() -> None:
    assert _validate_tag("  v2026.01.1  ") == "v2026.01.1"


def test_validate_tag_valid_high_micro() -> None:
    assert _validate_tag("v2025.12.99") == "v2025.12.99"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "2026.03.0",
        "v2026.3.0",
        "v2026.13.0",
        "v2026.00.0",
        "vabcd.01.0",
        "v2026.03",
        "v2026.03.0-beta",
    ],
)
def test_validate_tag_rejects_invalid(bad: str) -> None:
    with pytest.raises(ValueError):
        _validate_tag(bad)


# -- _validate_sha ------------------------------------------------------------


def test_validate_sha_valid() -> None:
    sha = "a" * 40
    assert _validate_sha(sha) == sha


def test_validate_sha_strips_whitespace() -> None:
    sha = "b" * 40
    assert _validate_sha(f"  {sha}  ") == sha


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "abc123",
        "g" * 40,
        "A" * 40,
        "a" * 39,
        "a" * 41,
    ],
)
def test_validate_sha_rejects_invalid(bad: str) -> None:
    with pytest.raises(ValueError):
        _validate_sha(bad)


# -- create_tag ---------------------------------------------------------------

_REPO = "owner/name"
_TAG = "v2026.03.0"
_SHA = "a" * 40
_TAG_OBJ_SHA = "b" * 40
_MESSAGE = "Release v2026.03.0"


def _make_create_tag_runner() -> QueueRunner:
    """Build a QueueRunner expecting the two-step create tag flow."""
    return QueueRunner(
        [
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "--method",
                    "POST",
                    f"/repos/{_REPO}/git/tags",
                    "--input",
                    "-",
                ],
                stdout=json.dumps({"sha": _TAG_OBJ_SHA, "tag": _TAG}),
                expected_input=json.dumps(
                    {
                        "tag": _TAG,
                        "message": _MESSAGE,
                        "object": _SHA,
                        "type": "commit",
                    }
                ),
            ),
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "--method",
                    "POST",
                    f"/repos/{_REPO}/git/refs",
                    "--input",
                    "-",
                ],
                stdout=json.dumps({"ref": f"refs/tags/{_TAG}"}),
                expected_input=json.dumps(
                    {
                        "ref": f"refs/tags/{_TAG}",
                        "sha": _TAG_OBJ_SHA,
                    }
                ),
            ),
        ]
    )


def test_create_tag_success() -> None:
    runner = _make_create_tag_runner()
    result = create_tag(
        runner=runner,
        repo=_REPO,
        tag=_TAG,
        sha=_SHA,
        message=_MESSAGE,
    )
    assert result["ok"] is True
    assert result["repo"] == _REPO
    assert result["tag"] == _TAG
    assert result["sha"] == _SHA
    assert result["tag_object_sha"] == _TAG_OBJ_SHA
    runner.assert_exhausted()


def test_create_tag_invalid_sha_from_api() -> None:
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=[
                    "gh",
                    "api",
                    "--method",
                    "POST",
                    f"/repos/{_REPO}/git/tags",
                    "--input",
                    "-",
                ],
                stdout=json.dumps({"sha": "not-a-valid-sha"}),
                expected_input=json.dumps(
                    {
                        "tag": _TAG,
                        "message": _MESSAGE,
                        "object": _SHA,
                        "type": "commit",
                    }
                ),
            ),
        ]
    )
    with pytest.raises(ValueError, match="invalid SHA"):
        create_tag(
            runner=runner,
            repo=_REPO,
            tag=_TAG,
            sha=_SHA,
            message=_MESSAGE,
        )
    runner.assert_exhausted()


def test_create_tag_rejects_invalid_tag() -> None:
    runner = QueueRunner([])
    with pytest.raises(ValueError, match="CalVer"):
        create_tag(
            runner=runner,
            repo=_REPO,
            tag="not-calver",
            sha=_SHA,
            message=_MESSAGE,
        )


def test_create_tag_rejects_invalid_sha() -> None:
    runner = QueueRunner([])
    with pytest.raises(ValueError, match="40-character"):
        create_tag(
            runner=runner,
            repo=_REPO,
            tag=_TAG,
            sha="tooshort",
            message=_MESSAGE,
        )


# -- _build_parser ------------------------------------------------------------


def test_build_parser_returns_parser_with_expected_args() -> None:
    parser = _build_parser()
    parsed = parser.parse_args(
        [
            "--tag",
            "v2026.03.0",
            "--sha",
            "a" * 40,
            "--message",
            "Release",
            "--repo",
            "owner/name",
            "--json",
        ]
    )
    assert parsed.tag == "v2026.03.0"
    assert parsed.sha == "a" * 40
    assert parsed.message == "Release"
    assert parsed.repo == "owner/name"
    assert parsed.json is True


def test_build_parser_defaults() -> None:
    parser = _build_parser()
    parsed = parser.parse_args(
        [
            "--tag",
            "v2026.01.0",
            "--sha",
            "b" * 40,
            "--message",
            "Tag",
        ]
    )
    assert parsed.repo is None
    assert parsed.json is False
