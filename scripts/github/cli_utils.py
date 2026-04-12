from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scripts.github.gh_cli import GhRunner


def normalize_nonempty_str(value: Any) -> str | None:
    """Return a stripped string, or None if value is not a non-empty string."""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if normalized else None


def casefold_nonempty_str(value: Any) -> str | None:
    """Return a casefolded string, or None if value is not a non-empty string."""
    normalized = normalize_nonempty_str(value)
    return normalized.casefold() if normalized else None


def read_optional_text(*, text: str | None, path: Path | None) -> str | None:
    """Read optional text from either a direct string or a UTF-8 text file.

    Behavior:
    - If both inputs are None -> returns None
    - If both inputs are provided -> raises ValueError
    - If path is provided -> reads UTF-8 from the file
    """
    if text is not None and path is not None:
        raise ValueError("Provide only one of --body or --body-file")
    if path is not None:
        return path.read_text(encoding="utf-8")
    return text


def read_required_text(*, text: str | None, path: Path | None) -> str:
    """Read required text from either a direct string or a UTF-8 text file."""
    out = read_optional_text(text=text, path=path)
    if out is None or not out.strip():
        raise ValueError("Body is required (use --body or --body-file)")
    return out


# -- Shared CLI scaffolding for repo+PR helpers ------------------------------


def build_repo_pr_parser(description: str) -> argparse.ArgumentParser:
    """Build an ActionableArgumentParser with --repo and --pr arguments.

    Both arguments are optional and default to auto-detection
    (current_repo / active_pr_number).
    """
    from scripts.github.gh_cli import ActionableArgumentParser

    parser = ActionableArgumentParser(description=description)
    parser.add_argument("--repo", default=None, help="Repo owner/name (default: auto-detect)")
    parser.add_argument("--pr", type=int, default=None, help="PR number (default: active PR)")
    return parser


@dataclass(frozen=True)
class RepoPr:
    """Resolved repo and PR number."""

    repo: str
    pr_number: int


def resolve_repo(args: argparse.Namespace, runner: GhRunner) -> str:
    """Resolve repo from CLI args with auto-detection fallback.

    Fallback chain: ``--repo`` arg → ``GITHUB_REPOSITORY`` env → ``gh repo view``.
    """
    from scripts.github.gh_cli import current_repo, default_repo_from_env

    return args.repo or default_repo_from_env() or current_repo(runner)


def resolve_repo_pr(args: argparse.Namespace, runner: GhRunner) -> RepoPr:
    """Resolve repo and PR number from CLI args with auto-detection fallback."""
    from scripts.github.gh_cli import active_pr_number

    repo = resolve_repo(args, runner)
    pr_number = args.pr or active_pr_number(runner)
    return RepoPr(repo=repo, pr_number=pr_number)


def resolve_body(args: argparse.Namespace) -> str | None:
    """Resolve body text from --body or --body-file CLI arguments."""
    return read_optional_text(text=args.body, path=args.body_file)
