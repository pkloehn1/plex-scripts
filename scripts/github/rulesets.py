"""Helpers for reading GitHub rulesets via `gh api`.

These helpers are read-only.
"""

from __future__ import annotations

from typing import Any

from scripts.github.gh_cli import GhRunner, as_dict, as_list, parse_repo, run_json


def _contexts_from_required_status_checks(rule: dict[str, Any]) -> set[str]:
    if rule.get("type") != "required_status_checks":
        return set()

    params = as_dict(rule.get("parameters"))
    checks = as_list(params.get("required_status_checks"))

    out: set[str] = set()
    for check in checks:
        check_dict = as_dict(check)
        ctx = check_dict.get("context")
        if isinstance(ctx, str) and ctx.strip():
            out.add(ctx.strip())
    return out


def list_rulesets(*, runner: GhRunner, repo: str) -> list[dict[str, Any]]:
    owner, name = parse_repo(repo)
    data = run_json(
        runner,
        [
            "gh",
            "api",
            "--paginate",
            f"/repos/{owner}/{name}/rulesets",
        ],
    )
    if not isinstance(data, list):
        raise ValueError("Unexpected rulesets payload")
    return [ruleset for ruleset in data if isinstance(ruleset, dict)]


def fetch_ruleset(*, runner: GhRunner, repo: str, ruleset_id: int) -> dict[str, Any]:
    owner, name = parse_repo(repo)
    data = run_json(runner, ["gh", "api", f"/repos/{owner}/{name}/rulesets/{ruleset_id}"])
    if not isinstance(data, dict):
        raise ValueError("Unexpected ruleset payload")
    return data


def required_status_check_contexts(ruleset: dict[str, Any]) -> set[str]:
    rules = as_list(ruleset.get("rules"))

    contexts: set[str] = set()
    for rule in rules:
        rule_dict = as_dict(rule)
        contexts |= _contexts_from_required_status_checks(rule_dict)

    return contexts
