"""Auto-generate structured PR body sections from branch commits.

Parses ``git log base..HEAD --oneline`` output, groups conventional commits
by type, and produces markdown that aligns with the repository's PR template
(``.github/pull_request_template.md``).

Section-scoped markers (``<!-- auto-summary:start/end -->``) allow safe
regeneration without overwriting manually-edited content.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from scripts.common.git_runner import GitResult, GitRunner
from scripts.devops.start_issue_work import parse_conventional_title
from scripts.github.gh_cli import CliOperationError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_AUTO_SUMMARY_START = "<!-- auto-summary:start -->"
_AUTO_SUMMARY_END = "<!-- auto-summary:end -->"

_DEPENDABOT_RE = re.compile(r"^Bump (the\b|[a-z])", re.IGNORECASE)

_TYPE_TO_CATEGORY: dict[str, str] = {
    "feat": "\U0001f680 Features",
    "fix": "\U0001f41b Bug Fixes",
    "perf": "\u26a1 Performance",
    "security": "\U0001f6e1\ufe0f Security",
    "refactor": "\U0001f69c Refactor",
    "docs": "\U0001f4d6 Documentation",
    "test": "\U0001f9ea Testing",
    "ci": "\U0001f527 CI/CD",
    "chore": "\u2699\ufe0f Miscellaneous",
    "style": "\U0001f3a8 Styling",
}

_CATEGORY_ORDER: list[str] = [
    "\U0001f680 Features",
    "\U0001f41b Bug Fixes",
    "\u26a1 Performance",
    "\U0001f6e1\ufe0f Security",
    "\U0001f69c Refactor",
    "\U0001f4d6 Documentation",
    "\U0001f9ea Testing",
    "\U0001f527 CI/CD",
    "\u2699\ufe0f Miscellaneous",
    "\U0001f3a8 Styling",
    "\U0001f4e6 Dependencies",
    "Other",
]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParsedCommit:
    """A single parsed commit from ``git log --oneline``."""

    sha: str
    type: str | None
    scope: str | None
    summary: str
    is_dependabot: bool


@dataclass(frozen=True)
class AutoSummary:
    """Result of auto-generating PR body sections."""

    summary_md: str
    full_body: str
    commit_count: int


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_commit_line(line: str) -> ParsedCommit | None:
    """Parse a single ``git log --oneline`` line into a :class:`ParsedCommit`.

    Returns ``None`` for empty or whitespace-only lines.
    """
    stripped = line.rstrip("\r\n").strip()
    if not stripped:
        return None

    # Split: <sha> <rest>
    parts = stripped.split(None, 1)
    if len(parts) < 2:
        return None

    sha, rest = parts[0], parts[1]

    # Detect Dependabot commits.
    is_dependabot = bool(_DEPENDABOT_RE.match(rest))

    # Attempt conventional commit parsing.
    typ, scope, summary = parse_conventional_title(rest)

    return ParsedCommit(
        sha=sha,
        type=typ,
        scope=scope,
        summary=summary,
        is_dependabot=is_dependabot,
    )


def parse_git_log_output(raw: str) -> list[ParsedCommit]:
    """Parse multi-line ``git log --oneline`` output."""
    commits: list[ParsedCommit] = []
    for line in raw.splitlines():
        parsed = parse_commit_line(line)
        if parsed is not None:
            commits.append(parsed)
    return commits


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------


def group_commits_by_category(
    commits: list[ParsedCommit],
) -> dict[str, list[ParsedCommit]]:
    """Group commits into ordered categories by conventional type."""
    buckets: dict[str, list[ParsedCommit]] = {}
    for commit in commits:
        if commit.is_dependabot:
            category = "\U0001f4e6 Dependencies"
        elif commit.type is not None:
            category = _TYPE_TO_CATEGORY.get(commit.type, "Other")
        else:
            category = "Other"

        buckets.setdefault(category, []).append(commit)

    # Return in defined order.
    ordered: dict[str, list[ParsedCommit]] = {}
    for cat in _CATEGORY_ORDER:
        if cat in buckets:
            ordered[cat] = buckets[cat]
    return ordered


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _format_commit_bullet(commit: ParsedCommit) -> str:
    """Format a commit as a summary bullet point."""
    if commit.scope:
        return f"- _({commit.scope})_ {commit.summary} ({commit.sha})"
    return f"- {commit.summary} ({commit.sha})"


def format_summary_section(grouped: dict[str, list[ParsedCommit]]) -> str:
    """Generate markdown for the Summary section (content between markers)."""
    if not grouped:
        return ""

    parts: list[str] = []
    for category, commits in grouped.items():
        parts.append(f"### {category}")
        for commit in commits:
            parts.append(_format_commit_bullet(commit))
        parts.append("")  # blank line after category
    return "\n".join(parts).rstrip("\n")


# ---------------------------------------------------------------------------
# PR body assembly
# ---------------------------------------------------------------------------


def build_pr_body(
    *,
    summary_md: str,
    issue_numbers: list[int] | None,
) -> str:
    """Assemble a full PR body from auto-generated sections and the PR template."""
    # Linked issues section.
    if issue_numbers:
        linked = "\n".join(f"Closes #{num}" for num in issue_numbers)
    else:
        linked = "Closes #ISSUE_NUMBER"

    return (
        f"## Summary\n\n"
        f"{_AUTO_SUMMARY_START}\n{summary_md}\n{_AUTO_SUMMARY_END}\n\n"
        f"## Dependencies\n\n- None\n\n"
        f"## Linked issues\n\n{linked}\n"
    )


# ---------------------------------------------------------------------------
# Section-scoped marker replacement
# ---------------------------------------------------------------------------

_MARKER_BLOCK_RE = re.compile(
    re.escape(_AUTO_SUMMARY_START) + r"\n.*?\n" + re.escape(_AUTO_SUMMARY_END),
    re.DOTALL,
)


def replace_auto_summary_blocks(
    existing_body: str,
    new_summary_md: str,
) -> str:
    """Replace content between auto-summary markers, preserving everything else.

    Replaces every ``<!-- auto-summary:start/end -->`` marker pair with
    *new_summary_md*.  If no markers are found, returns *existing_body*
    unchanged.
    """
    matches = list(_MARKER_BLOCK_RE.finditer(existing_body))
    if not matches:
        return existing_body

    result = existing_body
    # Replace in reverse order to preserve offsets.
    for match in reversed(matches):
        block = f"{_AUTO_SUMMARY_START}\n{new_summary_md}\n{_AUTO_SUMMARY_END}"
        result = result[: match.start()] + block + result[match.end() :]
    return result


def refresh_auto_summary_in_body(
    *,
    existing_body: str,
    git_runner: GitRunner,
    base_branch: str | None = None,
) -> str:
    """Regenerate auto-summary markers in an existing PR body.

    Detects the base branch (if not provided), parses branch commits,
    generates grouped summary and replaces any
    ``<!-- auto-summary:start/end -->`` marker blocks.  Content outside
    markers is preserved.
    """
    if not existing_body or _AUTO_SUMMARY_START not in existing_body:
        return existing_body
    base = base_branch or detect_base_branch(runner=git_runner)
    commits = get_branch_commits(runner=git_runner, base_branch=base)
    summary = generate_auto_summary(commits)
    return replace_auto_summary_blocks(
        existing_body,
        new_summary_md=summary.summary_md,
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def generate_auto_summary(
    commits: list[ParsedCommit],
    *,
    issue_numbers: list[int] | None = None,
) -> AutoSummary:
    """Top-level pure function: commits -> :class:`AutoSummary`."""
    if not commits:
        summary_md = "No commits found ahead of base branch."
    else:
        grouped = group_commits_by_category(commits)
        summary_md = format_summary_section(grouped)

    full_body = build_pr_body(
        summary_md=summary_md,
        issue_numbers=issue_numbers,
    )

    return AutoSummary(
        summary_md=summary_md,
        full_body=full_body,
        commit_count=len(commits),
    )


# ---------------------------------------------------------------------------
# I/O wrappers
# ---------------------------------------------------------------------------


def get_branch_commits(
    *,
    runner: GitRunner,
    base_branch: str,
    cwd: Path | None = None,
) -> list[ParsedCommit]:
    """Run ``git log base..HEAD --oneline`` and parse the output."""
    result = runner.run_git(
        ["log", f"{base_branch}..HEAD", "--oneline"],
        cwd=cwd,
    )
    if result.returncode != 0:
        raise CliOperationError(f"git log failed (exit {result.returncode}): {result.stderr.strip()}")
    return parse_git_log_output(result.stdout)


def detect_base_branch(
    *,
    runner: GitRunner,
    cwd: Path | None = None,
) -> str:
    """Detect the base branch (``main`` preferred, ``master`` fallback)."""
    for candidate in ("main", "master"):
        result = runner.run_git(["rev-parse", "--verify", candidate], cwd=cwd)
        if result.returncode == 0:
            return candidate
    raise CliOperationError("Cannot detect base branch: neither 'main' nor 'master' exists")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> int:
    """Entry point for ``python -m scripts.github.pr_auto_summary``."""
    from scripts.common.git_runner import run_git

    class _DefaultGitRunner:
        def run_git(self, args: list[str], *, cwd: Path | None = None) -> GitResult:
            return run_git(args, cwd=cwd)

    parser = argparse.ArgumentParser(
        description="Auto-generate PR summary from branch commits.",
    )
    parser.add_argument("--base", default=None, help="Base branch (default: auto-detect)")
    parser.add_argument(
        "--issue",
        type=int,
        action="append",
        default=None,
        help="Issue number(s) for Linked Issues section (repeatable)",
    )
    parser.add_argument("--output", type=Path, default=None, help="Write output to file")
    parser.add_argument("--json", action="store_true", help="Output structured JSON")

    args = parser.parse_args()
    git_runner = _DefaultGitRunner()

    base = args.base or detect_base_branch(runner=git_runner)
    commits = get_branch_commits(runner=git_runner, base_branch=base)
    summary = generate_auto_summary(commits, issue_numbers=args.issue)

    if args.json:
        data = {
            "commit_count": summary.commit_count,
            "summary_md": summary.summary_md,
            "full_body": summary.full_body,
        }
        output_text = json.dumps(data, indent=2, sort_keys=True)
    else:
        output_text = summary.full_body

    if args.output:
        args.output.write_text(output_text, encoding="utf-8")
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(output_text)

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
