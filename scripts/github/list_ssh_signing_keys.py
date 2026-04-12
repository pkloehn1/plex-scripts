#!/usr/bin/env python3
"""List SSH signing keys for the authenticated GitHub user.

Use case:
- When PR commits show verification reason `no_user`, GitHub likely cannot map the
    signing key used for the commit signature to a GitHub account.
- This script helps confirm which SSH signing keys GitHub currently knows about
    for the `gh` authenticated user.

This script is read-only.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from scripts.github.gh_cli import (
    ActionableArgumentParser,
    GhCliError,
    GhRunner,
    SubprocessGhRunner,
    print_actionable_cli_error,
    run_json,
)


def list_ssh_signing_keys(*, runner: GhRunner) -> list[dict[str, Any]]:
    data = run_json(runner, ["gh", "api", "--paginate", "/user/ssh_signing_keys"])
    if not isinstance(data, list):
        raise ValueError("Unexpected ssh_signing_keys payload")

    out: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "key": item.get("key"),
                "created_at": item.get("created_at"),
            }
        )

    return out


def _build_parser() -> argparse.ArgumentParser:
    parser = ActionableArgumentParser(description="List SSH signing keys for the gh user.")
    parser.add_argument(
        "--redact",
        action="store_true",
        help="Redact key material in output (keeps only first/last 8 chars)",
    )
    return parser


def _parse_args() -> argparse.Namespace:
    return _build_parser().parse_args()


def _redact_key(key: str) -> str:
    if len(key) <= 20:
        return "***"
    return f"{key[:8]}...{key[-8:]}"


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    runner = SubprocessGhRunner()

    try:
        keys = list_ssh_signing_keys(runner=runner)

        if args.redact:
            for item in keys:
                key = item.get("key")
                if isinstance(key, str) and key:
                    item["key"] = _redact_key(key)

        print(json.dumps({"count": len(keys), "keys": keys}, indent=2, sort_keys=True))
        return 0
    except (GhCliError, ValueError) as exc:
        print_actionable_cli_error(
            exc,
            parser=parser,
            examples=[
                "python -m scripts.github.list_ssh_signing_keys",
                "python -m scripts.github.list_ssh_signing_keys --redact",
            ],
            see_also=["scripts/github/README.md"],
        )
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
