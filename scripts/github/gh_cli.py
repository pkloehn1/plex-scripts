#!/usr/bin/env python3
"""Thin, testable wrapper around the GitHub CLI (`gh`).

Design goals:
- No shell invocation (pass argv lists to subprocess).
- Prefer JSON in/out so callers can avoid brittle `--jq` pipelines.
- Provide actionable error messages on failed API calls.

This module is intentionally small and dependency-free.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class CliOperationError(RuntimeError):
    """Raised when an expected CLI operation fails (git command, branch detection, etc.).

    Caught by :func:`run_actionable_main` alongside :class:`GhCliError` and
    ``ValueError`` so that expected operational failures produce actionable
    messages rather than stack traces.  Unexpected ``RuntimeError`` subclasses
    still propagate loudly.
    """


class GhCliError(CliOperationError):
    def __init__(
        self,
        message: str,
        *,
        argv: list[str],
        returncode: int,
        stdout: str,
        stderr: str,
    ) -> None:
        super().__init__(message)
        self.argv = argv
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


_GH_HELPERS_DEBUG_ENV = "GH_HELPERS_DEBUG"
_GH_HELPERS_DEBUG_MAX_CHARS_ENV = "GH_HELPERS_DEBUG_MAX_CHARS"


def gh_diagnostics_enabled(*, environ: Mapping[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    raw = env.get(_GH_HELPERS_DEBUG_ENV)
    if raw is None:
        return False
    value = raw.strip().lower()
    return value in {"1", "true", "yes", "y", "on"}


def gh_diagnostics_max_chars(*, environ: Mapping[str, str] | None = None) -> int | None:
    env = os.environ if environ is None else environ
    raw = env.get(_GH_HELPERS_DEBUG_MAX_CHARS_ENV)
    if raw is None or not raw.strip():
        return 50_000
    value = raw.strip().lower()
    if value in {"none", "null", "unlimited"}:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return 50_000
    if parsed <= 0:
        return 50_000
    return parsed


def format_gh_cli_error(
    err: GhCliError,
    *,
    max_chars: int | None = 50_000,
) -> str:
    """Return a human-readable string with argv, returncode, stdout, stderr.

    This is meant for surfacing actionable diagnostics when a gh invocation fails.
    """

    def _clip(label: str, text: str) -> str:
        normalized = text.rstrip("\n")
        if max_chars is not None and len(normalized) > max_chars:
            clipped = normalized[: max_chars - 1] + "…"
            return f"{label} (clipped to {max_chars} chars):\n{clipped}"
        return f"{label}:\n{normalized}" if normalized else f"{label}: (empty)"

    argv_str = " ".join(err.argv)
    parts = [
        "gh command failed",
        f"returncode: {err.returncode}",
        f"argv: {argv_str}",
        _clip("stdout", err.stdout),
        _clip("stderr", err.stderr),
    ]
    return "\n".join(parts)


def print_gh_cli_error(
    err: GhCliError,
    *,
    max_chars: int | None = 50_000,
) -> None:
    """Print a formatted GhCliError to stderr."""
    print(format_gh_cli_error(err, max_chars=max_chars), file=sys.stderr)


def format_actionable_cli_error(
    err: Exception,
    *,
    parser: argparse.ArgumentParser,
    examples: list[str] | None = None,
    see_also: list[str] | None = None,
) -> str:
    """Format a consistent, actionable CLI error message for scripts/github tools."""
    parts: list[str] = []
    parts.append(f"Error: {err}")

    if isinstance(err, GhCliError):
        # Keep default output concise; diagnostics can be enabled via GH_HELPERS_DEBUG.
        stderr = err.stderr.strip()
        if stderr:
            parts.append(f"\nDetails:\n{stderr}")
        parts.append("\nTip: set GH_HELPERS_DEBUG=1 to print gh argv/returncode/stdout/stderr diagnostics.")

    parts.append("\nAvailable options:\n")
    parts.append(parser.format_help().rstrip())

    if examples:
        parts.append("\nExample usage:")
        parts.extend([f"- {item}" for item in examples])

    if see_also:
        parts.append("\nSee also:")
        parts.extend([f"- {item}" for item in see_also])

    return "\n".join(parts).rstrip() + "\n"


def print_actionable_cli_error(
    err: Exception,
    *,
    parser: argparse.ArgumentParser,
    examples: list[str] | None = None,
    see_also: list[str] | None = None,
) -> None:
    print(
        format_actionable_cli_error(err, parser=parser, examples=examples, see_also=see_also),
        file=sys.stderr,
    )


class ActionableArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that raises ValueError instead of exiting on parse errors.

    This allows callers to print consistent, actionable errors including --help output.
    """

    def error(self, message: str) -> None:  # type: ignore[override]
        raise ValueError(message)


@dataclass(frozen=True)
class GhResult:
    stdout: str
    stderr: str


class GhRunner(Protocol):
    def run(self, argv: list[str], *, input_text: str | None = None) -> GhResult: ...


class SubprocessGhRunner:
    def run(self, argv: list[str], *, input_text: str | None = None) -> GhResult:
        result = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            input=input_text,
        )
        if result.returncode != 0:
            err = GhCliError(
                "gh command failed",
                argv=argv,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
            if gh_diagnostics_enabled():
                print_gh_cli_error(err, max_chars=gh_diagnostics_max_chars())
            raise err
        return GhResult(stdout=result.stdout, stderr=result.stderr)


def repo_root() -> Path:
    from scripts.common.paths import repo_root as _repo_root

    return _repo_root()


def _strip_json_output(text: str) -> str:
    # gh sometimes prints trailing newlines; JSON parser is tolerant, but keep stable.
    return text.strip()


def run_text(runner: GhRunner, argv: list[str], *, input_text: str | None = None) -> str:
    return runner.run(argv, input_text=input_text).stdout


def run_json(runner: GhRunner, argv: list[str], *, input_text: str | None = None) -> Any:
    raw = run_text(runner, argv, input_text=input_text)
    return json.loads(_strip_json_output(raw) or "null")


def run_actionable_main(
    *,
    build_parser: Callable[[], argparse.ArgumentParser],
    handler: Callable[[argparse.Namespace, argparse.ArgumentParser, GhRunner], int],
    examples: list[str] | None = None,
    see_also: list[str] | None = None,
    runner_factory: Callable[[], GhRunner] = SubprocessGhRunner,
) -> int:
    """Run a CLI handler with standardized actionable error handling.

    - Parses args using an ActionableArgumentParser (raises ValueError on errors).
    - Instantiates a GhRunner via `runner_factory`.
    - Delegates to `handler(args, parser, runner)`.
    - Formats errors via print_actionable_cli_error, or JSON when args.json is true.
    """
    parser = build_parser()
    args: argparse.Namespace | None = None
    try:
        args = parser.parse_args()
        runner = runner_factory()
        return handler(args, parser, runner)
    except (ValueError, CliOperationError) as exc:
        if args is not None and getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
            return 2
        print_actionable_cli_error(
            exc,
            parser=parser,
            examples=examples,
            see_also=see_also,
        )
        return 2


def current_repo(runner: GhRunner) -> str:
    """Return current repository as `owner/name`.

    Relies on gh detecting the repo from the git remote.
    """
    data = run_json(runner, ["gh", "repo", "view", "--json", "nameWithOwner"])
    name_with_owner = data.get("nameWithOwner") if isinstance(data, dict) else None
    if not isinstance(name_with_owner, str) or not name_with_owner.strip():
        raise ValueError("Unable to determine current repo via gh repo view")
    return name_with_owner.strip()


def active_pr_number(runner: GhRunner) -> int:
    """Return PR number associated with the current branch (via `gh pr view`)."""
    data = run_json(runner, ["gh", "pr", "view", "--json", "number"])
    number = data.get("number") if isinstance(data, dict) else None
    if not isinstance(number, int) or number <= 0:
        raise ValueError("Unable to determine active PR number via gh pr view")
    return number


def parse_repo(repo: str) -> tuple[str, str]:
    parts = repo.split("/", 1)
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        raise ValueError("repo must be in owner/name form")
    return parts[0].strip(), parts[1].strip()


def default_repo_from_env() -> str | None:
    repo = os.environ.get("GITHUB_REPOSITORY")
    if isinstance(repo, str) and repo.strip():
        return repo.strip()
    return None


def current_login(runner: GhRunner) -> str:
    """Return the GitHub login of the currently authenticated user."""
    payload = run_json(runner, ["gh", "api", "/user"])
    login = payload.get("login") if isinstance(payload, dict) else None
    if not isinstance(login, str) or not login.strip():
        raise ValueError("Unable to determine current login via gh api /user")
    return login.strip()


def as_dict(value: Any) -> dict[str, Any]:
    """Safely coerce to dict; returns ``{}`` for non-dict values."""
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    """Safely coerce to list; returns ``[]`` for non-list values."""
    return value if isinstance(value, list) else []
