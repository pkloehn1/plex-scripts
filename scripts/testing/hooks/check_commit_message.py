"""Pre-commit commit-msg hook to validate conventional commit format.

Validates that commit messages follow the conventional commit specification
(``type(scope): summary`` or ``type: summary``). This ensures commit messages
are parseable by the auto-summary generator (``scripts.github.pr_auto_summary``).

Exit codes:
    0: Message is valid (conventional commit, Dependabot, or merge commit)
    1: Message does not follow conventional commit format

Usage (pre-commit commit-msg stage):
    python scripts/testing/hooks/check_commit_message.py <commit-msg-file>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_DEPENDABOT_RE = re.compile(r"^Bump (the\b|[a-z])", re.IGNORECASE)
_MERGE_RE = re.compile(r"^Merge ")
_CONVENTIONAL_RE = re.compile(r"^[a-z]+(\([^)]+\))?: .+")


def validate_commit_message(message: str) -> tuple[bool, str]:
    """Validate a commit message against conventional commit format.

    Returns (is_valid, reason).
    """
    lines = message.strip().splitlines()
    if not lines:
        return False, "Commit message is empty"

    subject = lines[0].strip()

    # Allow merge commits.
    if _MERGE_RE.match(subject):
        return True, "Merge commit"

    # Allow Dependabot commits.
    if _DEPENDABOT_RE.match(subject):
        return True, "Dependabot commit"

    # Validate conventional commit format.
    if _CONVENTIONAL_RE.match(subject):
        return True, "Conventional commit"

    return False, (
        f"Subject line does not follow conventional commit format: {subject!r}\n"
        "Expected: type(scope): summary  or  type: summary\n"
        "Examples: feat(ci): add auto-summary, fix: resolve crash, docs: update README"
    )


def main() -> int:
    """Entry point for commit-msg hook."""
    if len(sys.argv) < 2:
        print("Usage: check_commit_message.py <commit-msg-file>", file=sys.stderr)
        return 2

    msg_path = Path(sys.argv[1])
    if not msg_path.exists():
        print(f"Commit message file not found: {msg_path}", file=sys.stderr)
        return 2

    message = msg_path.read_text(encoding="utf-8", errors="replace")
    is_valid, reason = validate_commit_message(message)

    if not is_valid:
        print(f"FAIL: {reason}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())  # pragma: no cover
