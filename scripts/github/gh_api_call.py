#!/usr/bin/env python3
"""Call a small allowlist of `gh api` endpoints with structured output.

Use case:
- Reduce trial/error on common GitHub API endpoints by producing:
    - the exact argv executed
    - parsed JSON when available
    - stderr/stdout on error

Security note:
- Endpoints are selected from a fixed allowlist. User input is limited to
    validated primitives (repo, integers, SHA).
"""

from __future__ import annotations

import argparse
import json
import re
from typing import Any

from scripts.github.cli_utils import resolve_repo
from scripts.github.gh_cli import (
    ActionableArgumentParser,
    GhCliError,
    SubprocessGhRunner,
    parse_repo,
    print_actionable_cli_error,
    run_text,
)

_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")


def _validate_sha(sha: str) -> str:
    if not _SHA_RE.fullmatch(sha):
        raise ValueError("sha must be a hex commit SHA (7-40 chars)")
    return sha


def _build_parser() -> argparse.ArgumentParser:
    parser = ActionableArgumentParser(description="Call common gh api endpoints safely.")
    parser.add_argument("--repo", default=None, help="Repo owner/name (default: auto-detect)")
    parser.add_argument(
        "--op",
        required=True,
        choices=[
            "issue",
            "pr",
            "pr-comment",
            "ruleset",
            "commit-status",
            "check-runs",
            "check-run-annotations",
        ],
        help="Which endpoint to call",
    )
    parser.add_argument("--number", type=int, help="Issue/PR number (when applicable)")
    parser.add_argument("--comment-id", type=int, help="PR review comment id (when applicable)")
    parser.add_argument("--ruleset-id", type=int, help="Ruleset id (when applicable)")
    parser.add_argument("--check-run-id", type=int, help="Check run id (when applicable)")
    parser.add_argument("--sha", help="Commit SHA (when applicable)")
    return parser


def _parse_args() -> argparse.Namespace:
    return _build_parser().parse_args()


def _require_positive_int(*, value: Any, flag: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"{flag} is required and must be positive")
    return value


def _require_sha(*, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("--sha is required")
    return _validate_sha(value.strip())


def _endpoint_for_op(*, owner: str, name: str, args: argparse.Namespace) -> str:
    operation = args.op

    if operation == "issue":
        number = _require_positive_int(value=args.number, flag="--number")
        return f"/repos/{owner}/{name}/issues/{number}"

    if operation == "pr":
        number = _require_positive_int(value=args.number, flag="--number")
        return f"/repos/{owner}/{name}/pulls/{number}"

    if operation == "pr-comment":
        comment_id = _require_positive_int(value=args.comment_id, flag="--comment-id")
        return f"/repos/{owner}/{name}/pulls/comments/{comment_id}"

    if operation == "ruleset":
        ruleset_id = _require_positive_int(value=args.ruleset_id, flag="--ruleset-id")
        return f"/repos/{owner}/{name}/rulesets/{ruleset_id}"

    if operation == "commit-status":
        sha = _require_sha(value=args.sha)
        return f"/repos/{owner}/{name}/commits/{sha}/status"

    if operation == "check-runs":
        sha = _require_sha(value=args.sha)
        return f"/repos/{owner}/{name}/commits/{sha}/check-runs"

    if operation == "check-run-annotations":
        check_run_id = _require_positive_int(value=args.check_run_id, flag="--check-run-id")
        return f"/repos/{owner}/{name}/check-runs/{check_run_id}/annotations"

    raise ValueError("Unsupported op")


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    runner = SubprocessGhRunner()

    try:
        repo = resolve_repo(args, runner)
        owner, name = parse_repo(repo)
        endpoint = _endpoint_for_op(owner=owner, name=name, args=args)
        argv: list[str] = ["gh", "api", endpoint]

        raw = run_text(runner, argv)
        try:
            parsed: Any = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None

        print(
            json.dumps(
                {
                    "ok": True,
                    "argv": argv,
                    "json": parsed,
                    "stdout": raw,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except (GhCliError, ValueError) as error:
        print_actionable_cli_error(
            error,
            parser=parser,
            examples=[
                "python -m scripts.github.gh_api_call --repo owner/name --op pr --number 123",
                "python -m scripts.github.gh_api_call --repo owner/name --op commit-status --sha abcdef0",
            ],
            see_also=["scripts/github/README.md"],
        )
        print(json.dumps({"ok": False, "error": str(error)}, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
