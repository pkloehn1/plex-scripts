#!/usr/bin/env python3
"""Close a GitHub issue via the REST API.

Why this exists:
- Repo policy is to interact with GitHub via ``scripts/github/*`` helpers
    rather than calling ``gh`` directly.
- Provides a testable, CLI-accessible way to close issues with an optional
    comment and a close reason (completed | not_planned).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.github.cli_utils import read_optional_text, resolve_repo
from scripts.github.gh_cli import (
    ActionableArgumentParser,
    GhRunner,
    parse_repo,
    run_actionable_main,
    run_json,
)

_VALID_REASONS = ("completed", "not_planned")


def close_issue(
    *,
    runner: GhRunner,
    repo: str,
    number: int,
    reason: str = "completed",
    comment: str | None = None,
) -> dict[str, object]:
    """Close a GitHub issue, optionally posting a comment first.

    Returns:
        Dict with ``ok``, ``repo``, ``number``, ``reason``, ``commented``.
    """
    if number <= 0:
        raise ValueError("number must be positive")
    if reason not in _VALID_REASONS:
        raise ValueError(f"reason must be one of {_VALID_REASONS}")

    owner, name = parse_repo(repo)

    commented = False
    if comment is not None and comment.strip():
        run_json(
            runner,
            [
                "gh",
                "api",
                "--method",
                "POST",
                f"/repos/{owner}/{name}/issues/{number}/comments",
                "-f",
                f"body={comment}",
            ],
        )
        commented = True

    run_json(
        runner,
        [
            "gh",
            "api",
            "--method",
            "PATCH",
            f"/repos/{owner}/{name}/issues/{number}",
            "-f",
            "state=closed",
            "-f",
            f"state_reason={reason}",
        ],
    )

    return {
        "ok": True,
        "repo": repo,
        "number": number,
        "reason": reason,
        "commented": commented,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = ActionableArgumentParser(description="Close a GitHub issue.")
    parser.add_argument("--repo", default=None, help="Repo owner/name (default: auto-detect)")
    parser.add_argument("--number", type=int, required=True, help="Issue number")
    parser.add_argument(
        "--reason",
        choices=list(_VALID_REASONS),
        default="completed",
        help="Close reason (default: completed)",
    )
    parser.add_argument("--comment", help="Optional comment to post before closing.")
    parser.add_argument(
        "--comment-file",
        type=Path,
        help="Path to a UTF-8 file containing the comment text.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    return parser


def _run(args: argparse.Namespace, _parser: argparse.ArgumentParser, runner: GhRunner) -> int:
    repo = resolve_repo(args, runner)
    comment = read_optional_text(text=args.comment, path=args.comment_file)

    payload = close_issue(
        runner=runner,
        repo=repo,
        number=args.number,
        reason=args.reason,
        comment=comment,
    )

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Closed issue #{args.number} in {repo} ({args.reason}).")

    return 0


def main() -> int:
    return run_actionable_main(
        build_parser=_build_parser,
        handler=_run,
        examples=[
            "python -m scripts.github.issue_close --repo owner/name --number 123",
            "python -m scripts.github.issue_close --repo owner/name --number 123 --reason not_planned",
            "python -m scripts.github.issue_close --repo owner/name --number 123 --comment 'Done.'",
        ],
        see_also=["scripts/github/README.md"],
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
