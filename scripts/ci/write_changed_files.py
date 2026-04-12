#!/usr/bin/env python3
"""Write `changed-files.txt` for CI workflows.

This script computes a list of changed paths for the current GitHub Actions run
and writes them to `changed-files.txt` in the repository root. It is intended to
support workflows that must always emit a stable check context.

Inputs:

- `GITHUB_EVENT_NAME`: event type (e.g., `pull_request`, `push`).
- `GITHUB_EVENT_PATH`: JSON payload path for the event (if available).

Output:

- `changed-files.txt`: newline-delimited file paths (with a trailing newline if
    non-empty).

Fail-open behavior:

- If change detection fails (git errors, unreadable event payload, etc.), the
    script writes a sentinel path that forces downstream decision logic to run the
    heavier validation steps rather than incorrectly skipping them.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TypeGuard

from scripts.ci.event_payload import read_event_payload as _read_event_payload
from scripts.common.paths import repo_root as _repo_root

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_ALLOWED_GIT_SUBCOMMANDS = frozenset({"diff-tree", "ls-files", "rev-list"})
_ALLOWED_STATIC_ARGS = frozenset(
    {
        "--stdin",
        "--name-only",
        "--parents",
        "--no-commit-id",
        "-n",
        "-r",
        "1",
        "HEAD",
        "--",
    }
)


@dataclass(frozen=True)
class ChangedFilesResult:
    """Typed result from changed-files discovery."""

    files: tuple[str, ...]
    is_fail_open: bool
    strategy: str


def _is_valid_sha(value: str | None) -> TypeGuard[str]:
    return value is not None and bool(_SHA_RE.match(value))


def _run_git(args: list[str], *, input_text: str | None = None) -> str:
    """Execute a git command with strict argument validation.

    Every element of *args* must be in the static allowlist.  Dynamic
    values (commit SHAs) must be passed via *input_text* (piped to
    stdin) to prevent argument injection.
    """
    if not args or args[0] not in _ALLOWED_GIT_SUBCOMMANDS:
        msg = f"git subcommand not allowed: {args[0] if args else '<empty>'}"
        raise ValueError(msg)
    rejected = [arg for arg in args[1:] if arg not in _ALLOWED_STATIC_ARGS]
    if rejected:
        msg = f"git argument(s) not in allowlist: {rejected}"
        raise ValueError(msg)
    result = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        input=input_text,
    )
    return result.stdout


def _diff_tree_stdin(input_text: str) -> list[str]:
    """Compare trees/commits via stdin and return changed file paths.

    Always includes ``--no-commit-id`` so stdout contains only paths.
    """
    return _run_git(
        ["diff-tree", "--stdin", "-r", "--name-only", "--no-commit-id"],
        input_text=input_text,
    ).splitlines()


def _fail_open_changed_files() -> list[str]:
    # Downstream decision logic uses fnmatch globs that look for stack compose
    # files. Provide a path that matches those globs to force running the heavy
    # validation steps when we cannot reliably determine the change set.
    return ["stacks/__unknown__/docker-compose.yml"]


def _ls_files_or_fail_open() -> list[str]:
    try:
        return _run_git(["ls-files"]).splitlines()
    except subprocess.CalledProcessError:
        return _fail_open_changed_files()


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _get_changed_files_for_pull_request(
    base_sha: str | None,
    head_sha: str | None,
) -> list[str]:
    # Default `actions/checkout` behavior for pull_request is to checkout the
    # merge commit (two parents). Prefer a purely local diff.
    try:
        parents_line = _run_git(["rev-list", "--parents", "-n", "1", "HEAD"]).strip()
        parts = parents_line.split()
        # parts: [merge_sha, parent1, parent2]
        if len(parts) >= 3 and _is_valid_sha(parts[1]) and _is_valid_sha(parts[2]):
            return _diff_tree_stdin(f"{parts[1]} {parts[2]}\n")
    except subprocess.CalledProcessError:
        # If we cannot compute the local merge-parent diff, fall back to SHAs
        # from the event payload.
        pass

    # Fallback: try base/head SHAs from the event payload.
    if _is_valid_sha(base_sha) and _is_valid_sha(head_sha):
        try:
            return _diff_tree_stdin(f"{base_sha} {head_sha}\n")
        except subprocess.CalledProcessError:
            # If diffing the payload SHAs fails, fall back to a conservative list.
            pass

    # Last resort: be conservative.
    try:
        return _run_git(["ls-files"]).splitlines()
    except subprocess.CalledProcessError:
        return _fail_open_changed_files()


def _get_changed_files_for_push(before: str | None, after: str | None) -> list[str]:
    before = str(before or "")
    after = str(after or "")

    if not _is_valid_sha(before) or not _is_valid_sha(after):
        return _ls_files_or_fail_open()

    # GitHub uses 40 zeros for the "before" SHA on the initial commit.
    if before == "0" * 40:
        try:
            return _diff_tree_stdin(f"{after}\n")
        except subprocess.CalledProcessError:
            return _ls_files_or_fail_open()

    try:
        return _diff_tree_stdin(f"{before} {after}\n")
    except subprocess.CalledProcessError:
        return _ls_files_or_fail_open()


def discover_changed_files() -> ChangedFilesResult:
    """Discover changed files and return a typed result with metadata.

    Returns a :class:`ChangedFilesResult` including the file list, the detection
    strategy used, and whether the fail-open sentinel was emitted.
    """
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    payload = _read_event_payload()

    try:
        if event_name in {"pull_request", "merge_group"}:
            if event_name == "pull_request":
                base_sha = payload.get("pull_request", {}).get("base", {}).get("sha")
                head_sha = payload.get("pull_request", {}).get("head", {}).get("sha")
            else:
                # merge_group payload fields live at the top-level.
                base_sha = payload.get("base_sha")
                head_sha = payload.get("head_sha")

            files = _get_changed_files_for_pull_request(base_sha, head_sha)
            strategy = event_name
        elif event_name == "push":
            files = _get_changed_files_for_push(payload.get("before"), payload.get("after"))
            strategy = "push"
        else:
            files = _run_git(["ls-files"]).splitlines()
            strategy = "ls-files"
    except subprocess.CalledProcessError:
        files = _fail_open_changed_files()
        strategy = "fail-open"

    normalized = [path.strip() for path in files if path and path.strip()]
    deduped = _dedupe_preserve_order(normalized)
    is_fail_open = deduped == _fail_open_changed_files()
    return ChangedFilesResult(
        files=tuple(deduped),
        is_fail_open=is_fail_open,
        strategy=strategy,
    )


def get_changed_files() -> list[str]:
    """Return the list of changed files (convenience wrapper)."""
    return list(discover_changed_files().files)


def write_changed_files(repo_root: Path, changed_files: list[str]) -> Path:
    out_path = repo_root / "changed-files.txt"
    out_path.write_text(
        "\n".join(changed_files) + ("\n" if changed_files else ""),
        encoding="utf-8",
    )
    return out_path


def main() -> int:
    repo_root = _repo_root()
    os.chdir(repo_root)

    changed_files = get_changed_files()
    out_path = write_changed_files(repo_root, changed_files)
    print(f"Wrote {len(changed_files)} changed file paths to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
