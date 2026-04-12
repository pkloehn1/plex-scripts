"""CalVer versioning: compute YYYY.0M.MICRO versions from git tags."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from scripts.common.git_runner import GitResult, GitRunner, run_git
from scripts.common.paths import repo_root

EXIT_OK = 0
EXIT_FAILED = 1

CALVER_TAG_RE = re.compile(r"^v(\d{4})\.(\d{2})\.(\d+)$")


@dataclass(frozen=True)
class CalVerResult:
    """Computed CalVer version."""

    version: str
    tag: str
    year: int
    month: int
    micro: int

    def __iter__(self) -> Iterator[str | int]:
        """Allow tuple unpacking: ``version, tag, year, month, micro = result``."""
        yield self.version
        yield self.tag
        yield self.year
        yield self.month
        yield self.micro


def parse_calver_tag(tag_str: str) -> CalVerResult | None:
    """Parse a CalVer tag string into a CalVerResult.

    Returns None for tags that do not match ``vYYYY.0M.MICRO`` format
    or have an invalid month (must be 01-12).
    """
    match = CALVER_TAG_RE.match(tag_str)
    if not match:
        return None
    year, month, micro = int(match.group(1)), int(match.group(2)), int(match.group(3))
    if month < 1 or month > 12:
        return None
    version = f"{year}.{month:02d}.{micro}"
    return CalVerResult(version=version, tag=tag_str, year=year, month=month, micro=micro)


def compute_next_version(existing_tags: list[str], now: datetime) -> CalVerResult:
    """Compute the next CalVer version from existing tags and current time.

    Pure function: no I/O, no side effects.
    """
    year = now.year
    month = now.month

    same_period = [
        parsed
        for tag in existing_tags
        if (parsed := parse_calver_tag(tag)) is not None and parsed.year == year and parsed.month == month
    ]

    micro = max(entry.micro for entry in same_period) + 1 if same_period else 0

    version = f"{year}.{month:02d}.{micro}"
    tag = f"v{version}"
    return CalVerResult(version=version, tag=tag, year=year, month=month, micro=micro)


def list_tags(runner: GitRunner, *, cwd: Path | None = None) -> list[str]:
    """List all git tags matching the ``v*`` pattern."""
    result = runner.run_git(["tag", "--list", "v*"], cwd=cwd)
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


class _DefaultGitRunner:
    """Adapter satisfying GitRunner Protocol using the module-level run_git."""

    def run_git(self, args: list[str], *, cwd: Path | None = None) -> GitResult:
        return run_git(args, cwd=cwd)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute next CalVer version from git tags.")
    parser.add_argument("--dry-run", action="store_true", help="Print version string only")
    return parser.parse_args(argv)


def main(
    argv: list[str],
    *,
    runner: GitRunner | None = None,
    now: datetime | None = None,
) -> int:
    """CLI entry point for CalVer computation."""
    args = _parse_args(argv)
    cwd = repo_root()

    effective_runner = runner if runner is not None else _DefaultGitRunner()
    effective_now = now if now is not None else datetime.now(tz=UTC)

    tags = list_tags(effective_runner, cwd=cwd)
    result = compute_next_version(tags, effective_now)

    if args.dry_run:
        print(result.version)
    else:
        print(f"version={result.version}")
        print(f"tag={result.tag}")

    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
