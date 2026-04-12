#!/usr/bin/env python3
"""List GitHub rulesets and required status check contexts.

Use case:
- Reduce time spent guessing exact required check context names.

This script is read-only.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass

from scripts.github.cli_utils import resolve_repo
from scripts.github.gh_cli import (
    ActionableArgumentParser,
    GhCliError,
    GhRunner,
    SubprocessGhRunner,
    print_actionable_cli_error,
)
from scripts.github.rulesets import (
    fetch_ruleset,
    list_rulesets,
    required_status_check_contexts,
)


@dataclass(frozen=True)
class RulesetRequiredContexts:
    ruleset_id: int
    name: str
    enforcement: str | None
    required_contexts: list[str]


def list_required_contexts(*, runner: GhRunner, repo: str) -> list[RulesetRequiredContexts]:
    out: list[RulesetRequiredContexts] = []
    for ruleset in list_rulesets(runner=runner, repo=repo):
        rid = ruleset.get("id")
        rname = ruleset.get("name")
        enforcement = ruleset.get("enforcement")
        if not isinstance(rid, int) or not isinstance(rname, str):
            continue

        full = fetch_ruleset(runner=runner, repo=repo, ruleset_id=rid)
        contexts = sorted(required_status_check_contexts(full))

        out.append(
            RulesetRequiredContexts(
                ruleset_id=rid,
                name=rname,
                enforcement=enforcement if isinstance(enforcement, str) else None,
                required_contexts=contexts,
            )
        )

    return out


def _parse_args() -> argparse.Namespace:
    return _build_parser().parse_args()


def _build_parser() -> argparse.ArgumentParser:
    parser = ActionableArgumentParser(description="List rulesets and required status check contexts.")
    parser.add_argument("--repo", default=None, help="Repo owner/name (default: auto-detect)")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    runner = SubprocessGhRunner()

    try:
        repo = resolve_repo(args, runner)
        payload = [ruleset.__dict__ for ruleset in list_required_contexts(runner=runner, repo=repo)]
        print(json.dumps({"repo": repo, "rulesets": payload}, indent=2, sort_keys=True))
        return 0
    except (GhCliError, ValueError) as exc:
        print_actionable_cli_error(
            exc,
            parser=parser,
            examples=[
                "python -m scripts.github.list_rulesets_required_contexts --repo owner/name",
            ],
            see_also=["scripts/github/README.md"],
        )
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
