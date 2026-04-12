"""Tests for diff_required_status_contexts module."""

from __future__ import annotations

import argparse
import json
from typing import Any

import pytest

from scripts.github.conftest import ExpectedCall, QueueRunner
from scripts.github.diff_required_status_contexts import (
    ContextDiff,
    _build_parser,
    _head_sha,
    _present_status_contexts,
    _required_contexts_union,
    _run,
    diff_required_contexts,
    main,
)

# -- helpers -------------------------------------------------------------------

REPO = "octo/widgets"
PR_NUMBER = 42
HEAD_SHA = "abc123def456"


def _pr_view_argv(pr_number: int = PR_NUMBER) -> list[str]:
    return [
        "gh",
        "pr",
        "view",
        str(pr_number),
        "--repo",
        REPO,
        "--json",
        "commits",
    ]


def _list_rulesets_argv() -> list[str]:
    return ["gh", "api", "--paginate", "/repos/octo/widgets/rulesets"]


def _fetch_ruleset_argv(ruleset_id: int) -> list[str]:
    return ["gh", "api", f"/repos/octo/widgets/rulesets/{ruleset_id}"]


def _status_argv(sha: str = HEAD_SHA) -> list[str]:
    return ["gh", "api", f"/repos/octo/widgets/commits/{sha}/status"]


def _pr_view_call(commits: list[dict] | None = None) -> ExpectedCall:
    if commits is None:
        commits = [{"oid": HEAD_SHA}]
    return ExpectedCall(
        argv=_pr_view_argv(),
        stdout=json.dumps({"commits": commits}),
    )


# -- _head_sha -----------------------------------------------------------------


def test_head_sha_success() -> None:
    runner = QueueRunner([_pr_view_call()])
    result = _head_sha(runner=runner, repo=REPO, pr_number=PR_NUMBER)
    assert result == HEAD_SHA
    runner.assert_exhausted()


def test_head_sha_strips_whitespace() -> None:
    runner = QueueRunner([_pr_view_call([{"oid": f"  {HEAD_SHA}  "}])])
    result = _head_sha(runner=runner, repo=REPO, pr_number=PR_NUMBER)
    assert result == HEAD_SHA


def test_head_sha_empty_commits_raises() -> None:
    runner = QueueRunner([_pr_view_call([])])
    with pytest.raises(ValueError, match="Unable to read PR commits"):
        _head_sha(runner=runner, repo=REPO, pr_number=PR_NUMBER)


def test_head_sha_non_list_commits_raises() -> None:
    call = ExpectedCall(
        argv=_pr_view_argv(),
        stdout=json.dumps({"commits": "not-a-list"}),
    )
    runner = QueueRunner([call])
    with pytest.raises(ValueError, match="Unable to read PR commits"):
        _head_sha(runner=runner, repo=REPO, pr_number=PR_NUMBER)


def test_head_sha_missing_commits_key_raises() -> None:
    call = ExpectedCall(
        argv=_pr_view_argv(),
        stdout=json.dumps({"other": "data"}),
    )
    runner = QueueRunner([call])
    with pytest.raises(ValueError, match="Unable to read PR commits"):
        _head_sha(runner=runner, repo=REPO, pr_number=PR_NUMBER)


def test_head_sha_non_string_oid_raises() -> None:
    runner = QueueRunner([_pr_view_call([{"oid": 12345}])])
    with pytest.raises(ValueError, match="Unable to determine head SHA"):
        _head_sha(runner=runner, repo=REPO, pr_number=PR_NUMBER)


def test_head_sha_blank_oid_raises() -> None:
    runner = QueueRunner([_pr_view_call([{"oid": "   "}])])
    with pytest.raises(ValueError, match="Unable to determine head SHA"):
        _head_sha(runner=runner, repo=REPO, pr_number=PR_NUMBER)


def test_head_sha_non_dict_payload_raises() -> None:
    call = ExpectedCall(argv=_pr_view_argv(), stdout=json.dumps([1, 2]))
    runner = QueueRunner([call])
    with pytest.raises(ValueError, match="Unable to read PR commits"):
        _head_sha(runner=runner, repo=REPO, pr_number=PR_NUMBER)


# -- _required_contexts_union --------------------------------------------------


def test_required_contexts_union_combines_rulesets() -> None:
    rulesets = [{"id": 1}, {"id": 2}]
    detail_one = {
        "rules": [
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [{"context": "ci/build"}],
                },
            }
        ]
    }
    detail_two = {
        "rules": [
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [{"context": "ci/test"}],
                },
            }
        ]
    }
    runner = QueueRunner(
        [
            ExpectedCall(argv=_list_rulesets_argv(), stdout=json.dumps(rulesets)),
            ExpectedCall(argv=_fetch_ruleset_argv(1), stdout=json.dumps(detail_one)),
            ExpectedCall(argv=_fetch_ruleset_argv(2), stdout=json.dumps(detail_two)),
        ]
    )
    result = _required_contexts_union(runner=runner, repo=REPO)
    assert result == {"ci/build", "ci/test"}
    runner.assert_exhausted()


def test_required_contexts_union_skips_non_int_id() -> None:
    rulesets: list[dict[str, Any]] = [{"id": "bad"}, {"id": 3}]
    detail: dict[str, Any] = {"rules": []}
    runner = QueueRunner(
        [
            ExpectedCall(argv=_list_rulesets_argv(), stdout=json.dumps(rulesets)),
            ExpectedCall(argv=_fetch_ruleset_argv(3), stdout=json.dumps(detail)),
        ]
    )
    result = _required_contexts_union(runner=runner, repo=REPO)
    assert result == set()
    runner.assert_exhausted()


def test_required_contexts_union_empty_rulesets() -> None:
    runner = QueueRunner([ExpectedCall(argv=_list_rulesets_argv(), stdout=json.dumps([]))])
    result = _required_contexts_union(runner=runner, repo=REPO)
    assert result == set()
    runner.assert_exhausted()


# -- _present_status_contexts --------------------------------------------------


def test_present_status_contexts_extracts_contexts() -> None:
    payload = {
        "statuses": [
            {"context": "ci/build"},
            {"context": "ci/test"},
        ]
    }
    runner = QueueRunner([ExpectedCall(argv=_status_argv(), stdout=json.dumps(payload))])
    result = _present_status_contexts(runner=runner, repo=REPO, sha=HEAD_SHA)
    assert result == {"ci/build", "ci/test"}
    runner.assert_exhausted()


def test_present_status_contexts_non_list_statuses_returns_empty() -> None:
    payload = {"statuses": "not-a-list"}
    runner = QueueRunner([ExpectedCall(argv=_status_argv(), stdout=json.dumps(payload))])
    result = _present_status_contexts(runner=runner, repo=REPO, sha=HEAD_SHA)
    assert result == set()


def test_present_status_contexts_non_dict_payload_returns_empty() -> None:
    runner = QueueRunner([ExpectedCall(argv=_status_argv(), stdout=json.dumps([1, 2]))])
    result = _present_status_contexts(runner=runner, repo=REPO, sha=HEAD_SHA)
    assert result == set()


def test_present_status_contexts_skips_non_dict_items() -> None:
    payload = {"statuses": ["not-a-dict", {"context": "ci/build"}]}
    runner = QueueRunner([ExpectedCall(argv=_status_argv(), stdout=json.dumps(payload))])
    result = _present_status_contexts(runner=runner, repo=REPO, sha=HEAD_SHA)
    assert result == {"ci/build"}


def test_present_status_contexts_skips_non_string_context() -> None:
    payload = {"statuses": [{"context": 999}, {"context": "ci/lint"}]}
    runner = QueueRunner([ExpectedCall(argv=_status_argv(), stdout=json.dumps(payload))])
    result = _present_status_contexts(runner=runner, repo=REPO, sha=HEAD_SHA)
    assert result == {"ci/lint"}


def test_present_status_contexts_skips_blank_context() -> None:
    payload = {"statuses": [{"context": "   "}, {"context": "ci/lint"}]}
    runner = QueueRunner([ExpectedCall(argv=_status_argv(), stdout=json.dumps(payload))])
    result = _present_status_contexts(runner=runner, repo=REPO, sha=HEAD_SHA)
    assert result == {"ci/lint"}


def test_present_status_contexts_strips_whitespace() -> None:
    payload = {"statuses": [{"context": "  ci/build  "}]}
    runner = QueueRunner([ExpectedCall(argv=_status_argv(), stdout=json.dumps(payload))])
    result = _present_status_contexts(runner=runner, repo=REPO, sha=HEAD_SHA)
    assert result == {"ci/build"}


# -- diff_required_contexts ----------------------------------------------------


def test_diff_required_contexts_full_orchestration() -> None:
    pr_view_payload = {"commits": [{"oid": HEAD_SHA}]}
    rulesets = [{"id": 10}]
    ruleset_detail = {
        "rules": [
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [
                        {"context": "ci/build"},
                        {"context": "ci/test"},
                    ],
                },
            }
        ]
    }
    status_payload = {
        "statuses": [
            {"context": "ci/build"},
            {"context": "ci/deploy"},
        ]
    }
    runner = QueueRunner(
        [
            ExpectedCall(argv=_pr_view_argv(), stdout=json.dumps(pr_view_payload)),
            ExpectedCall(argv=_list_rulesets_argv(), stdout=json.dumps(rulesets)),
            ExpectedCall(argv=_fetch_ruleset_argv(10), stdout=json.dumps(ruleset_detail)),
            ExpectedCall(argv=_status_argv(), stdout=json.dumps(status_payload)),
        ]
    )
    result = diff_required_contexts(runner=runner, repo=REPO, pr_number=PR_NUMBER)
    assert result["repo"] == REPO
    assert result["pr"] == PR_NUMBER
    assert result["head_sha"] == HEAD_SHA
    diff = result["diff"]
    assert diff["required"] == ["ci/build", "ci/test"]
    assert diff["present"] == ["ci/build", "ci/deploy"]
    assert diff["missing"] == ["ci/test"]
    assert diff["extra"] == ["ci/deploy"]
    runner.assert_exhausted()


# -- ContextDiff ---------------------------------------------------------------


def test_context_diff_frozen() -> None:
    context_diff = ContextDiff(required=["a"], present=["b"], missing=["a"], extra=["b"])
    with pytest.raises(AttributeError):
        context_diff.required = []  # type: ignore[misc]


# -- _build_parser -------------------------------------------------------------


def test_build_parser_returns_argument_parser() -> None:
    parser = _build_parser()
    assert isinstance(parser, argparse.ArgumentParser)


# -- _run ----------------------------------------------------------------------


def test_run_prints_json_and_returns_zero(capsys) -> None:
    pr_view_payload = {"commits": [{"oid": HEAD_SHA}]}
    rulesets = [{"id": 5}]
    ruleset_detail = {
        "rules": [
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [{"context": "ci/lint"}],
                },
            }
        ]
    }
    status_payload = {"statuses": [{"context": "ci/lint"}]}
    runner = QueueRunner(
        [
            ExpectedCall(argv=_pr_view_argv(), stdout=json.dumps(pr_view_payload)),
            ExpectedCall(argv=_list_rulesets_argv(), stdout=json.dumps(rulesets)),
            ExpectedCall(argv=_fetch_ruleset_argv(5), stdout=json.dumps(ruleset_detail)),
            ExpectedCall(argv=_status_argv(), stdout=json.dumps(status_payload)),
        ]
    )
    args = argparse.Namespace(repo=REPO, pr=PR_NUMBER)
    exit_code = _run(args, _build_parser(), runner)
    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["repo"] == REPO
    assert output["diff"]["missing"] == []
    assert output["diff"]["extra"] == []
    runner.assert_exhausted()


# -- main ----------------------------------------------------------------------


def test_main_delegates_to_run_actionable_main(monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.github.diff_required_status_contexts.run_actionable_main",
        lambda **kwargs: 0,
    )
    assert main() == 0
