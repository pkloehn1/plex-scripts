"""Tests for rulesets module."""

from __future__ import annotations

import json
from typing import Any

import pytest

from scripts.github.conftest import ExpectedCall, QueueRunner
from scripts.github.rulesets import (
    _contexts_from_required_status_checks,
    fetch_ruleset,
    list_rulesets,
    required_status_check_contexts,
)

# -- _contexts_from_required_status_checks ------------------------------------


def test_contexts_returns_empty_for_wrong_rule_type() -> None:
    rule = {"type": "pull_request", "parameters": {}}
    assert _contexts_from_required_status_checks(rule) == set()


def test_contexts_extracts_check_names() -> None:
    rule = {
        "type": "required_status_checks",
        "parameters": {
            "required_status_checks": [
                {"context": "ci/build"},
                {"context": "ci/test"},
            ],
        },
    }
    assert _contexts_from_required_status_checks(rule) == {"ci/build", "ci/test"}


def test_contexts_skips_non_string_context() -> None:
    rule = {
        "type": "required_status_checks",
        "parameters": {
            "required_status_checks": [
                {"context": 123},
                {"context": "valid"},
            ],
        },
    }
    assert _contexts_from_required_status_checks(rule) == {"valid"}


def test_contexts_skips_empty_string_context() -> None:
    rule = {
        "type": "required_status_checks",
        "parameters": {
            "required_status_checks": [
                {"context": "  "},
            ],
        },
    }
    assert _contexts_from_required_status_checks(rule) == set()


def test_contexts_handles_empty_checks_list() -> None:
    rule = {
        "type": "required_status_checks",
        "parameters": {"required_status_checks": []},
    }
    assert _contexts_from_required_status_checks(rule) == set()


def test_contexts_handles_non_list_checks() -> None:
    rule = {
        "type": "required_status_checks",
        "parameters": {"required_status_checks": "not-a-list"},
    }
    assert _contexts_from_required_status_checks(rule) == set()


# -- list_rulesets ------------------------------------------------------------

_REPO = "owner/name"


def test_list_rulesets_returns_dict_items() -> None:
    payload = [{"id": 1, "name": "main"}, {"id": 2, "name": "release"}]
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=["gh", "api", "--paginate", f"/repos/{_REPO}/rulesets"],
                stdout=json.dumps(payload),
            ),
        ]
    )
    result = list_rulesets(runner=runner, repo=_REPO)
    assert result == payload
    runner.assert_exhausted()


def test_list_rulesets_filters_non_dict_items() -> None:
    payload = [{"id": 1}, "not-a-dict", 42]
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=["gh", "api", "--paginate", f"/repos/{_REPO}/rulesets"],
                stdout=json.dumps(payload),
            ),
        ]
    )
    result = list_rulesets(runner=runner, repo=_REPO)
    assert result == [{"id": 1}]
    runner.assert_exhausted()


def test_list_rulesets_raises_on_non_list_payload() -> None:
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=["gh", "api", "--paginate", f"/repos/{_REPO}/rulesets"],
                stdout=json.dumps({"unexpected": "dict"}),
            ),
        ]
    )
    with pytest.raises(ValueError, match="Unexpected rulesets payload"):
        list_rulesets(runner=runner, repo=_REPO)


# -- fetch_ruleset ------------------------------------------------------------


def test_fetch_ruleset_returns_dict() -> None:
    payload = {"id": 5, "name": "main-protection"}
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=["gh", "api", f"/repos/{_REPO}/rulesets/5"],
                stdout=json.dumps(payload),
            ),
        ]
    )
    result = fetch_ruleset(runner=runner, repo=_REPO, ruleset_id=5)
    assert result == payload
    runner.assert_exhausted()


def test_fetch_ruleset_raises_on_non_dict_payload() -> None:
    runner = QueueRunner(
        [
            ExpectedCall(
                argv=["gh", "api", f"/repos/{_REPO}/rulesets/5"],
                stdout=json.dumps([1, 2, 3]),
            ),
        ]
    )
    with pytest.raises(ValueError, match="Unexpected ruleset payload"):
        fetch_ruleset(runner=runner, repo=_REPO, ruleset_id=5)


# -- required_status_check_contexts -------------------------------------------


def test_required_status_check_contexts_aggregates_rules() -> None:
    ruleset = {
        "rules": [
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [{"context": "ci/build"}],
                },
            },
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [{"context": "ci/test"}],
                },
            },
            {"type": "pull_request"},
        ],
    }
    assert required_status_check_contexts(ruleset) == {"ci/build", "ci/test"}


def test_required_status_check_contexts_empty_rules() -> None:
    ruleset: dict[str, Any] = {"rules": []}
    assert required_status_check_contexts(ruleset) == set()
