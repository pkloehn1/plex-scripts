#!/usr/bin/env python3
"""Fix unsigned commits in a pull request by re-signing them.

This script:
1. Identifies unsigned commits in a PR
2. Verifies git signing configuration
3. Re-signs commits via interactive rebase
4. Optionally force-pushes the fixed commits (requires --apply flag)

Safety:
- Default is dry-run mode (--apply required to make changes)
- Force push uses --force-with-lease for safety
- Verifies signing config before attempting fixes
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from scripts.common.git_signing_utils import find_signing_key_path, git_config_value
from scripts.github.gh_cli import (
    GhCliError,
    GhRunner,
    SubprocessGhRunner,
    active_pr_number,
    current_repo,
    parse_repo,
    print_actionable_cli_error,
    run_json,
)
from scripts.github.list_pr_commit_verifications import (
    filter_commits,
    list_pr_commit_verifications,
)


def check_git_signing_config() -> dict[str, Any]:
    """Check git commit signing configuration.

    Returns:
        Dict with config status and values.
    """
    result: dict[str, Any] = {
        "configured": False,
        "commit_gpgsign": None,
        "gpg_format": None,
        "user_signingkey": None,
        "user_email": None,
        "user_name": None,
    }

    try:
        result["commit_gpgsign"] = git_config_value("commit.gpgsign")
        result["gpg_format"] = git_config_value("gpg.format")
        result["user_signingkey"] = git_config_value("user.signingkey")
        result["user_email"] = git_config_value("user.email")
        result["user_name"] = git_config_value("user.name")

        signingkey_path = find_signing_key_path(result["user_signingkey"])

        result["configured"] = (
            result["commit_gpgsign"] == "true"
            and result["gpg_format"] == "ssh"
            and signingkey_path is not None
            and signingkey_path.exists()
        )
        result["signingkey_path"] = str(signingkey_path) if signingkey_path else None

    except Exception as exc:
        result["error"] = str(exc)

    return result


def get_pr_branch_info(*, runner: GhRunner, repo: str, pr_number: int) -> dict[str, str | None]:
    """Get PR branch information (head ref and base ref)."""
    owner, name = parse_repo(repo)
    pr_data = run_json(
        runner,
        [
            "gh",
            "api",
            f"/repos/{owner}/{name}/pulls/{pr_number}",
        ],
    )
    if not isinstance(pr_data, dict):
        raise ValueError("Unexpected PR payload")

    head_ref = pr_data.get("head", {}).get("ref") if isinstance(pr_data.get("head"), dict) else None
    base_ref = pr_data.get("base", {}).get("ref") if isinstance(pr_data.get("base"), dict) else None

    if not isinstance(head_ref, str) or not head_ref.strip():
        raise ValueError("Unable to determine PR head ref")
    if not isinstance(base_ref, str) or not base_ref.strip():
        raise ValueError("Unable to determine PR base ref")

    return {
        "head_ref": head_ref.strip(),
        "base_ref": base_ref.strip(),
        "head_sha": pr_data.get("head", {}).get("sha") if isinstance(pr_data.get("head"), dict) else None,
    }


def verify_local_branch(*, branch: str) -> bool:
    """Verify the branch exists locally and is checked out."""
    result = subprocess.run(
        ["git", "rev-parse", "--verify", branch],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def get_current_branch() -> str | None:
    """Get the current git branch name."""
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def rebase_to_resign_commits(*, base_ref: str, apply: bool) -> dict[str, Any]:
    """Rebase commits to re-sign them.

    Uses interactive rebase with exec to automatically re-sign all commits.
    Cross-platform: uses Python script for sequence editor.
    """
    if not apply:
        return {
            "status": "dry_run",
            "message": "Would rebase to re-sign commits (use --apply to execute)",
        }

    # Fetch latest base branch
    fetch_result = subprocess.run(
        ["git", "fetch", "origin", base_ref],
        capture_output=True,
        text=True,
        check=False,
    )
    if fetch_result.returncode != 0:
        return {
            "status": "error",
            "error": f"Failed to fetch base branch: {fetch_result.stderr}",
        }

    # Create a temporary Python script to act as GIT_SEQUENCE_EDITOR
    # This converts all 'pick' lines to 'exec git commit --amend --no-edit --no-verify'
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        editor_script = Path(tmpdir) / "git_rebase_editor.py"
        editor_script.write_text(
            """# Inline script executed by the configured Python interpreter
import sys
import re

# Git passes the todo file path as sys.argv[1]
if len(sys.argv) < 2:
    sys.stderr.write("Error: expected todo file path as argument\\n")
    sys.exit(1)

todo_file = sys.argv[1]

# Read the rebase todo list from the file
with open(todo_file, 'r', encoding='utf-8') as f:
    content = f.read()

# Add 'exec git commit --amend --no-edit --no-verify' after each 'pick' line
# This re-signs each commit during rebase
# Pattern: replace 'pick <sha> <message>' with 'pick <sha> <message>\nexec git commit --amend --no-edit --no-verify'
modified = re.sub(
    r'^(pick [0-9a-fA-F]{7,40} .+)',
    r'\1\nexec git commit --amend --no-edit --no-verify',
    content,
    flags=re.MULTILINE,
)

with open(todo_file, 'w', encoding='utf-8') as f:
    f.write(modified)
"""
        )

        # TemporaryDirectory creates a 0o700 directory, so the file starts private.
        # Make script executable (Unix-like) with restrictive permissions (owner read/write/execute only).
        # On Windows, os.chmod is a no-op but doesn't fail; the temp dir already scopes access.
        if sys.platform != "win32":
            try:  # noqa: SIM105 — non-fatal; contextlib.suppress hides intent
                os.chmod(editor_script, 0o700)  # Owner: read, write, execute
            except OSError:
                pass

        # Set GIT_SEQUENCE_EDITOR to use our Python script
        env = dict(os.environ)
        python_cmd = sys.executable
        if sys.platform == "win32":
            # Use list2cmdline for Windows cmd/PowerShell compatibility.
            quoted = subprocess.list2cmdline([python_cmd, str(editor_script)])
        else:
            quoted = f"{shlex.quote(python_cmd)} {shlex.quote(str(editor_script))}"
        env["GIT_SEQUENCE_EDITOR"] = quoted

        rebase_result = subprocess.run(
            ["git", "rebase", "-i", f"origin/{base_ref}"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

        if rebase_result.returncode != 0:
            git_dir = Path(".git")
            if (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists():
                return {
                    "status": "conflict",
                    "error": "Rebase conflicts detected. Manual resolution required.",
                    "stderr": rebase_result.stderr,
                }
            return {
                "status": "error",
                "error": f"Rebase failed: {rebase_result.stderr}",
            }

        return {
            "status": "success",
            "message": "Commits re-signed successfully",
        }


def verify_commits_signed(*, count: int) -> dict[str, Any]:
    """Verify that recent commits are signed."""
    result = subprocess.run(
        ["git", "log", "--show-signature", f"-n{count}"],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        return {
            "status": "error",
            "error": f"Failed to verify signatures: {result.stderr}",
        }

    output = result.stdout

    # git's signature output varies between GPG and SSH formats, so use resilient
    # pattern matching instead of exact substring counts.
    good_signatures = len(re.findall(r"\bGood\b.*\bsignature\b", output, flags=re.I))
    bad_signatures = len(re.findall(r"\bBAD signature\b", output, flags=re.I))
    no_signatures = len(re.findall(r"\bNo signature\b", output, flags=re.I))

    is_verified = bad_signatures == 0 and no_signatures == 0 and good_signatures >= count

    payload: dict[str, Any] = {
        "good_signatures": good_signatures,
        "bad_signatures": bad_signatures,
        "no_signatures": no_signatures,
        "output": output,
    }

    if not is_verified:
        payload["status"] = "error"
        payload["error"] = (
            f"Signature verification indicates commits remain unsigned or invalid (expected {count} good signature(s))"
        )
        return payload

    payload["status"] = "success"
    return payload


def force_push_branch(*, branch: str, apply: bool) -> dict[str, Any]:
    """Force push the branch using --force-with-lease."""
    if not apply:
        return {
            "status": "dry_run",
            "message": f"Would force push {branch} (use --apply to execute)",
        }

    result = subprocess.run(
        ["git", "push", "--force-with-lease", "origin", branch],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        return {
            "status": "error",
            "error": f"Force push failed: {result.stderr}",
        }

    return {
        "status": "success",
        "message": f"Force pushed {branch} successfully",
    }


def fix_unsigned_commits(
    *,
    runner: GhRunner,
    repo: str,
    pr_number: int,
    apply: bool = False,
) -> dict[str, Any]:
    """Fix unsigned commits in a PR by re-signing them.

    Returns:
        Dict with status and details of the fix operation.
    """
    result: dict[str, Any] = {
        "repo": repo,
        "pr": pr_number,
        "apply": apply,
    }

    # Step 1: Check for unsigned commits
    commits = list_pr_commit_verifications(runner=runner, repo=repo, pr=pr_number)
    failing_commits = filter_commits(commits, only_failing=True)
    unsigned_count = len([commit for commit in failing_commits if commit.get("reason") == "unsigned"])

    result["unsigned_count"] = unsigned_count
    result["failing_count"] = len(failing_commits)
    result["total_commits"] = len(commits)

    if result["failing_count"] == 0:
        result["status"] = "no_action_needed"
        result["message"] = "No failing commits found"
        return result

    # Step 2: Verify git signing configuration
    signing_config = check_git_signing_config()
    result["signing_config"] = signing_config

    if not signing_config["configured"]:
        result["status"] = "error"
        result["error"] = "Git commit signing is not properly configured"
        result["config_help"] = {
            "commit_gpgsign": signing_config["commit_gpgsign"],
            "gpg_format": signing_config["gpg_format"],
            "user_signingkey": signing_config["user_signingkey"],
            "signingkey_path": signing_config.get("signingkey_path"),
            "required": {
                "commit.gpgsign": "true",
                "gpg.format": "ssh",
                "user.signingkey": "path to SSH public key",
            },
            "setup_command": ".venv/bin/python -m scripts.devops.setup_git_signing",
        }
        return result

    # Step 3: Get PR branch info
    try:
        branch_info = get_pr_branch_info(runner=runner, repo=repo, pr_number=pr_number)
        result["branch_info"] = branch_info
    except Exception as exc:
        result["status"] = "error"
        result["error"] = f"Failed to get PR branch info: {exc}"
        return result

    head_ref = cast(str, branch_info["head_ref"])
    base_ref = cast(str, branch_info["base_ref"])

    # Step 4: Verify local branch state
    current_branch = get_current_branch()
    if current_branch != head_ref:
        result["status"] = "error"
        result["error"] = (
            f"Current branch ({current_branch}) does not match PR head branch ({head_ref}). "
            f"Please checkout the PR branch first."
        )
        return result

    if not verify_local_branch(branch=head_ref):
        result["status"] = "error"
        result["error"] = f"Branch {head_ref} not found locally"
        return result

    # Step 5: Rebase to re-sign commits
    rebase_result = rebase_to_resign_commits(base_ref=base_ref, apply=apply)
    result["rebase"] = rebase_result

    if rebase_result.get("status") == "error":
        result["status"] = "error"
        return result

    if rebase_result.get("status") == "conflict":
        result["status"] = "conflict"
        return result

    if not apply:
        result["status"] = "dry_run"
        result["message"] = "Dry run complete. Use --apply to execute fixes."
        return result

    # Step 6: Verify commits are now signed
    verify_result = verify_commits_signed(count=result["failing_count"])
    result["verification"] = verify_result

    if verify_result.get("status") != "success":
        result["status"] = "error"
        result["error"] = "Rebase completed but commits are not verified as signed"
        return result

    # Step 7: Force push (if apply is True)
    push_result = force_push_branch(branch=head_ref, apply=apply)
    result["push"] = push_result

    if push_result.get("status") == "error":
        result["status"] = "error"
        return result

    result["status"] = "success"
    result["message"] = f"Fixed {result['failing_count']} failing commit(s) and pushed to {head_ref}"

    return result


def _build_parser() -> argparse.ArgumentParser:
    from scripts.github.gh_cli import ActionableArgumentParser

    parser = ActionableArgumentParser(description="Fix unsigned commits in a pull request by re-signing them.")
    parser.add_argument(
        "--repo",
        default=None,
        help="GitHub repo (owner/name). Defaults to current repo.",
    )
    parser.add_argument(
        "--pr",
        type=int,
        default=None,
        help="PR number. Defaults to active PR.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply fixes (default is dry-run). Required to actually rebase and push.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON (default: text)",
    )
    return parser


def _print_json_output(result: dict[str, Any]) -> int:
    """Print result as JSON and return appropriate exit code."""
    print(json.dumps(result, indent=2, sort_keys=True))
    status = result.get("status")
    if status == "error":
        return 1
    if status == "conflict":
        return 2
    return 0


def _print_text_output(result: dict[str, Any], args: argparse.Namespace) -> int:
    """Print result as text and return exit code."""
    status = result.get("status", "unknown")
    message = result.get("message", "")

    print(f"Status: {status}")
    if message:
        print(f"Message: {message}")

    if result.get("unsigned_count", 0) > 0:
        print(f"Unsigned commits: {result['unsigned_count']} of {result['total_commits']}")

    if "error" in result:
        print(f"Error: {result['error']}", file=sys.stderr)
        return 1

    if status == "error":
        return 1
    if status == "conflict":
        print("Rebase conflicts detected. Manual resolution required.", file=sys.stderr)
        return 2
    if status == "dry_run" and not args.apply:
        print("\nThis was a dry run. Use --apply to execute fixes.")
        return 0

    return 0


def main() -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args()
        runner = SubprocessGhRunner()

        repo = args.repo or current_repo(runner)
        pr_number = args.pr or active_pr_number(runner)

        result = fix_unsigned_commits(
            runner=runner,
            repo=repo,
            pr_number=pr_number,
            apply=args.apply,
        )

        if args.json:
            return _print_json_output(result)

        return _print_text_output(result, args)
    except (GhCliError, ValueError) as exc:
        error_result = {
            "status": "error",
            "message": str(exc),
            "error": str(exc),
        }
        if "args" in locals() and getattr(args, "json", False):  # type: ignore[name-defined]
            return _print_json_output(error_result)

        print_actionable_cli_error(
            exc,
            parser=parser,
            examples=[
                "python -m scripts.github.fix_unsigned_commits --pr 104",
                "python -m scripts.github.fix_unsigned_commits --pr 104 --apply",
            ],
            see_also=["scripts/github/README.md"],
        )
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
