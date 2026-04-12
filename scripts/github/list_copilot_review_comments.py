#!/usr/bin/env python3
"""List PR review comments authored by GitHub Copilot.

Use case:
- Quickly enumerate Copilot review comments (IDs + file/line) so they can be
    handled with the repo's reply/resolve automation.

This script is a compatibility wrapper.

Prefer:
- scripts.github.list_pr_review_comments_filtered (generic filters: author/body/path)
"""

from __future__ import annotations

import sys

from scripts.github.gh_cli import print_actionable_cli_error
from scripts.github.list_pr_review_comments_filtered import (
    _build_parser as _build_filtered_parser,
)
from scripts.github.list_pr_review_comments_filtered import main as _main_filtered


def main() -> int:
    # Rewrite argv to apply the default Copilot author filter, while allowing callers
    # to still pass --repo/--pr and any other shared args.
    #
    # This keeps existing workflows stable:
    #   python -m scripts.github.list_copilot_review_comments --repo ... --pr ...
    #
    # And delegates all behavior to the generic filtered script.
    parser = _build_filtered_parser()
    try:
        args = parser.parse_args()
        if not args.author_substring:
            sys.argv.extend(["--author-substring", "copilot"])
        return _main_filtered()
    except ValueError as exc:
        print_actionable_cli_error(
            exc,
            parser=parser,
            examples=[
                "python -m scripts.github.list_copilot_review_comments --repo owner/name --pr 123",
            ],
            see_also=["scripts/github/README.md"],
        )
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
