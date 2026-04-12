"""Tests for gh_api_call module."""

from __future__ import annotations

import argparse
import json

import pytest

from scripts.github.gh_api_call import (
    _build_parser,
    _endpoint_for_op,
    _parse_args,
    _require_positive_int,
    _require_sha,
    _validate_sha,
    main,
)
from scripts.github.gh_cli import GhCliError, GhResult

# -- _validate_sha -------------------------------------------------------------


def test_validate_sha_short() -> None:
    assert _validate_sha("abcdef0") == "abcdef0"


def test_validate_sha_full() -> None:
    assert _validate_sha("a" * 40) == "a" * 40


def test_validate_sha_too_short() -> None:
    with pytest.raises(ValueError, match="hex commit SHA"):
        _validate_sha("abc")


def test_validate_sha_non_hex() -> None:
    with pytest.raises(ValueError, match="hex commit SHA"):
        _validate_sha("ghijklm")


def test_validate_sha_too_long() -> None:
    with pytest.raises(ValueError, match="hex commit SHA"):
        _validate_sha("a" * 41)


# -- _build_parser / _parse_args -----------------------------------------------


def test_build_parser() -> None:
    assert isinstance(_build_parser(), argparse.ArgumentParser)


def test_parse_args(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["prog", "--op", "issue", "--number", "1", "--repo", "o/n"])
    args = _parse_args()
    assert args.op == "issue"
    assert args.number == 1


# -- _require_positive_int -----------------------------------------------------


def test_require_positive_int_valid() -> None:
    assert _require_positive_int(value=5, flag="--num") == 5


def test_require_positive_int_zero() -> None:
    with pytest.raises(ValueError, match="--num is required"):
        _require_positive_int(value=0, flag="--num")


def test_require_positive_int_none() -> None:
    with pytest.raises(ValueError, match="--flag is required"):
        _require_positive_int(value=None, flag="--flag")


def test_require_positive_int_non_int() -> None:
    with pytest.raises(ValueError, match="--flag is required"):
        _require_positive_int(value="5", flag="--flag")


# -- _require_sha --------------------------------------------------------------


def test_require_sha_valid() -> None:
    assert _require_sha(value="abcdef0") == "abcdef0"


def test_require_sha_strips() -> None:
    assert _require_sha(value="  abcdef0  ") == "abcdef0"


def test_require_sha_none() -> None:
    with pytest.raises(ValueError, match="--sha is required"):
        _require_sha(value=None)


def test_require_sha_empty() -> None:
    with pytest.raises(ValueError, match="--sha is required"):
        _require_sha(value="   ")


def test_require_sha_non_string() -> None:
    with pytest.raises(ValueError, match="--sha is required"):
        _require_sha(value=123)


# -- _endpoint_for_op ---------------------------------------------------------


def _make_args(**kwargs) -> argparse.Namespace:
    defaults = {"op": None, "number": None, "comment_id": None, "ruleset_id": None, "check_run_id": None, "sha": None}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


@pytest.mark.parametrize(
    ("op_name", "extra_kwargs", "expected_suffix"),
    [
        ("issue", {"number": 42}, "/repos/o/n/issues/42"),
        ("pr", {"number": 10}, "/repos/o/n/pulls/10"),
        ("pr-comment", {"comment_id": 99}, "/repos/o/n/pulls/comments/99"),
        ("ruleset", {"ruleset_id": 7}, "/repos/o/n/rulesets/7"),
        ("commit-status", {"sha": "abcdef0"}, "/repos/o/n/commits/abcdef0/status"),
        ("check-runs", {"sha": "1234567"}, "/repos/o/n/commits/1234567/check-runs"),
        ("check-run-annotations", {"check_run_id": 55}, "/repos/o/n/check-runs/55/annotations"),
    ],
)
def test_endpoint_for_op(op_name, extra_kwargs, expected_suffix) -> None:
    args = _make_args(op=op_name, **extra_kwargs)
    assert _endpoint_for_op(owner="o", name="n", args=args) == expected_suffix


def test_endpoint_unsupported_op() -> None:
    with pytest.raises(ValueError, match="Unsupported op"):
        _endpoint_for_op(owner="o", name="n", args=_make_args(op="unknown"))


@pytest.mark.parametrize(
    ("op_name", "match_text"),
    [
        ("issue", "--number is required"),
        ("pr", "--number is required"),
        ("pr-comment", "--comment-id is required"),
        ("ruleset", "--ruleset-id is required"),
        ("commit-status", "--sha is required"),
        ("check-runs", "--sha is required"),
        ("check-run-annotations", "--check-run-id is required"),
    ],
)
def test_endpoint_missing_required_param(op_name, match_text) -> None:
    with pytest.raises(ValueError, match=match_text):
        _endpoint_for_op(owner="o", name="n", args=_make_args(op=op_name))


# -- main ----------------------------------------------------------------------


def test_main_json_response(monkeypatch, capsys) -> None:
    api_resp = {"title": "Issue", "state": "open"}

    class _FakeRunner:
        def run(self, argv, *, input_text=None):
            return GhResult(stdout=json.dumps(api_resp), stderr="")

    monkeypatch.setattr("scripts.github.gh_api_call.SubprocessGhRunner", _FakeRunner)
    monkeypatch.setattr("sys.argv", ["prog", "--repo", "o/n", "--op", "issue", "--number", "42"])
    assert main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True
    assert output["json"]["title"] == "Issue"


def test_main_non_json_response(monkeypatch, capsys) -> None:
    class _FakeRunner:
        def run(self, argv, *, input_text=None):
            return GhResult(stdout="not json", stderr="")

    monkeypatch.setattr("scripts.github.gh_api_call.SubprocessGhRunner", _FakeRunner)
    monkeypatch.setattr("sys.argv", ["prog", "--repo", "o/n", "--op", "issue", "--number", "1"])
    assert main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["json"] is None
    assert output["stdout"] == "not json"


def test_main_value_error(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.argv", ["prog", "--repo", "o/n", "--op", "issue"])
    assert main() == 2


def test_main_gh_cli_error(monkeypatch, capsys) -> None:
    class _ErrorRunner:
        def run(self, argv, *, input_text=None):
            raise GhCliError("fail", argv=argv, returncode=1, stdout="", stderr="oops")

    monkeypatch.setattr("scripts.github.gh_api_call.SubprocessGhRunner", _ErrorRunner)
    monkeypatch.setattr("sys.argv", ["prog", "--repo", "o/n", "--op", "pr", "--number", "5"])
    assert main() == 2
    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is False
