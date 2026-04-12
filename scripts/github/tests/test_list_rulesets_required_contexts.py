"""Tests for list_rulesets_required_contexts module."""

from __future__ import annotations

import argparse
import json

import pytest

from scripts.github.conftest import ExpectedCall, QueueRunner
from scripts.github.gh_cli import GhCliError, GhResult
from scripts.github.list_rulesets_required_contexts import (
    RulesetRequiredContexts,
    _build_parser,
    _parse_args,
    list_required_contexts,
    main,
)


def _list_argv() -> list[str]:
    return ["gh", "api", "--paginate", "/repos/o/n/rulesets"]


def _detail_argv(rid: int) -> list[str]:
    return ["gh", "api", f"/repos/o/n/rulesets/{rid}"]


# -- RulesetRequiredContexts ---------------------------------------------------


def test_dataclass_frozen() -> None:
    ctx = RulesetRequiredContexts(ruleset_id=1, name="r", enforcement="active", required_contexts=["ci"])
    with pytest.raises(AttributeError):
        ctx.name = "x"  # type: ignore[misc]


# -- list_required_contexts ----------------------------------------------------


def test_single_ruleset() -> None:
    rulesets = [{"id": 1, "name": "protect", "enforcement": "active"}]
    detail = {
        "rules": [{"type": "required_status_checks", "parameters": {"required_status_checks": [{"context": "ci"}]}}]
    }
    runner = QueueRunner(
        [
            ExpectedCall(argv=_list_argv(), stdout=json.dumps(rulesets)),
            ExpectedCall(argv=_detail_argv(1), stdout=json.dumps(detail)),
        ]
    )
    result = list_required_contexts(runner=runner, repo="o/n")
    assert len(result) == 1
    assert result[0].required_contexts == ["ci"]
    runner.assert_exhausted()


def test_skips_invalid_id() -> None:
    rulesets = [{"id": "bad", "name": "r"}, {"id": 2, "name": "ok", "enforcement": "active"}]
    runner = QueueRunner(
        [
            ExpectedCall(argv=_list_argv(), stdout=json.dumps(rulesets)),
            ExpectedCall(argv=_detail_argv(2), stdout=json.dumps({"rules": []})),
        ]
    )
    result = list_required_contexts(runner=runner, repo="o/n")
    assert len(result) == 1
    runner.assert_exhausted()


def test_skips_invalid_name() -> None:
    rulesets = [{"id": 1, "name": 999}]
    runner = QueueRunner([ExpectedCall(argv=_list_argv(), stdout=json.dumps(rulesets))])
    assert list_required_contexts(runner=runner, repo="o/n") == []


def test_non_string_enforcement_becomes_none() -> None:
    rulesets = [{"id": 1, "name": "r", "enforcement": 123}]
    runner = QueueRunner(
        [
            ExpectedCall(argv=_list_argv(), stdout=json.dumps(rulesets)),
            ExpectedCall(argv=_detail_argv(1), stdout=json.dumps({"rules": []})),
        ]
    )
    result = list_required_contexts(runner=runner, repo="o/n")
    assert result[0].enforcement is None


def test_missing_enforcement_becomes_none() -> None:
    rulesets = [{"id": 1, "name": "r"}]
    runner = QueueRunner(
        [
            ExpectedCall(argv=_list_argv(), stdout=json.dumps(rulesets)),
            ExpectedCall(argv=_detail_argv(1), stdout=json.dumps({"rules": []})),
        ]
    )
    result = list_required_contexts(runner=runner, repo="o/n")
    assert result[0].enforcement is None


def test_empty_rulesets() -> None:
    runner = QueueRunner([ExpectedCall(argv=_list_argv(), stdout="[]")])
    assert list_required_contexts(runner=runner, repo="o/n") == []


# -- _build_parser / _parse_args -----------------------------------------------


def test_build_parser() -> None:
    assert isinstance(_build_parser(), argparse.ArgumentParser)


def test_parse_args(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["prog", "--repo", "o/n"])
    assert _parse_args().repo == "o/n"


# -- main ----------------------------------------------------------------------


def test_main_success(monkeypatch, capsys) -> None:
    rulesets = [{"id": 1, "name": "protect", "enforcement": "active"}]
    detail = {
        "rules": [{"type": "required_status_checks", "parameters": {"required_status_checks": [{"context": "ci"}]}}]
    }

    class _FakeRunner:
        def run(self, argv, *, input_text=None):
            raw = argv[-1]
            if raw.endswith("/rulesets"):
                return GhResult(stdout=json.dumps(rulesets), stderr="")
            return GhResult(stdout=json.dumps(detail), stderr="")

    monkeypatch.setattr("scripts.github.list_rulesets_required_contexts.SubprocessGhRunner", _FakeRunner)
    monkeypatch.setattr("sys.argv", ["prog", "--repo", "o/n"])
    assert main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["repo"] == "o/n"
    assert len(output["rulesets"]) == 1


def test_main_gh_cli_error(monkeypatch) -> None:
    class _ErrorRunner:
        def run(self, argv, *, input_text=None):
            raise GhCliError("fail", argv=argv, returncode=1, stdout="", stderr="oops")

    monkeypatch.setattr("scripts.github.list_rulesets_required_contexts.SubprocessGhRunner", _ErrorRunner)
    monkeypatch.setattr("sys.argv", ["prog", "--repo", "o/n"])
    assert main() == 2


def test_main_value_error_bad_repo(monkeypatch) -> None:
    monkeypatch.setattr("scripts.github.list_rulesets_required_contexts.SubprocessGhRunner", lambda: QueueRunner([]))
    monkeypatch.setattr("sys.argv", ["prog", "--repo", "badrepo"])
    assert main() == 2
