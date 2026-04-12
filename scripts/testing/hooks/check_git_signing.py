#!/usr/bin/env python3
"""Pre-commit hook to verify Git commit signing is configured.

Exit codes:
    0: Signing is configured or check is skipped
    1: Signing is not configured (blocks commit)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.common.git_signing_utils import find_signing_key_path, git_config_value


def _log(msg: str) -> None:
    """Write a diagnostic line to stderr for signing troubleshooting."""
    sys.stderr.write(f"[check-git-signing] {msg}\n")


def _test_signing(signingkey_path: Path) -> tuple[bool, str]:
    """Attempt a real signature to verify signing works end-to-end."""
    _log(f"smoke test: ssh-keygen -Y sign -f {signingkey_path}")
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
        test_file = Path(tmp.name)
        sig_file = Path(tmp.name + ".sig")
        tmp.write(b"signing-test\n")
    try:
        result = subprocess.run(
            ["ssh-keygen", "-Y", "sign", "-f", str(signingkey_path), "-n", "git", str(test_file)],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if result.returncode == 0:
            _log("smoke test: signing succeeded")
            return True, "Signing capability verified"
        _log(f"smoke test: signing failed (rc={result.returncode}): {result.stderr.strip()}")
        return False, f"Signing capability check failed: {result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        _log("smoke test: signing timed out after 10s")
        return False, (
            "Signing timed out (stale SSH_AUTH_SOCK?). "
            "Run: unset SSH_AUTH_SOCK (PowerShell: Remove-Item Env:SSH_AUTH_SOCK)"
        )
    except FileNotFoundError:
        _log("smoke test: ssh-keygen not found on PATH")
        return False, "ssh-keygen not found; cannot verify signing capability"
    finally:
        test_file.unlink(missing_ok=True)
        sig_file.unlink(missing_ok=True)


def _check_ssh_program() -> tuple[bool, str] | None:
    """Check gpg.ssh.program (e.g. 1Password op-ssh-sign) if configured.

    When ``gpg.ssh.program`` points to a valid binary (e.g. 1Password
    ``op-ssh-sign``), an existence check is performed.  A signing smoke
    test is deliberately **not** run because 1Password triggers a
    biometric approval prompt that requires user interaction — running it
    inside a pre-commit hook would block the hook chain.

    Returns a result tuple when gpg.ssh.program is set, or ``None`` to
    fall through to the ssh-keygen smoke test.
    """
    ssh_program = git_config_value("gpg.ssh.program")
    if not ssh_program:
        _log("gpg.ssh.program: not configured (falling through to ssh-keygen test)")
        return None
    resolved_path = Path(ssh_program)
    if resolved_path.exists():
        _log(f"gpg.ssh.program: found at {ssh_program}")
        return True, f"Git commit signing configured (gpg.ssh.program={ssh_program})"
    which_result = shutil.which(ssh_program)
    if which_result:
        _log(f"gpg.ssh.program: resolved via PATH to {which_result}")
        return True, f"Git commit signing configured (gpg.ssh.program={which_result})"
    _log(f"gpg.ssh.program: NOT FOUND — {ssh_program} does not exist and is not on PATH")
    return False, f"gpg.ssh.program not found: {ssh_program}"


def check_git_signing() -> tuple[bool, str]:
    """Check if Git commit signing is properly configured."""
    try:
        commit_gpgsign = git_config_value("commit.gpgsign")
        _log(f"commit.gpgsign = {commit_gpgsign!r}")
        # git config --get returns the raw stored string; git accepts
        # True/TRUE as boolean values but stores them as-is.  We require
        # the canonical lowercase "true" set by setup_git_signing.py.
        if commit_gpgsign != "true":
            return False, "commit.gpgsign is not set to 'true'"

        gpg_format = git_config_value("gpg.format")
        _log(f"gpg.format = {gpg_format!r}")
        if gpg_format != "ssh":
            return False, f"gpg.format is '{gpg_format}' (expected 'ssh')"

        user_signingkey = git_config_value("user.signingkey")
        _log(f"user.signingkey = {user_signingkey!r}")
        if not user_signingkey:
            return False, "user.signingkey is not set"

        signingkey_path = find_signing_key_path(user_signingkey)
        _log(f"resolved signing key path: {signingkey_path}")
        if not signingkey_path or not signingkey_path.exists():
            return False, f"Signing key file not found: {user_signingkey}"

        program_result = _check_ssh_program()
        if program_result is not None:
            return program_result

        sign_ok, sign_msg = _test_signing(signingkey_path)
        if not sign_ok:
            return False, sign_msg

        return True, "Git commit signing is properly configured"

    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        _log(f"unexpected error: {type(exc).__name__}: {exc}")
        return False, (f"Error checking git signing configuration ({type(exc).__name__}): {exc}")


def main() -> int:
    """Main entry point."""
    # Allow skipping this check via environment variable
    if "SKIP_GIT_SIGNING_CHECK" in os.environ:
        return 0

    is_configured, message = check_git_signing()

    if is_configured:
        return 0

    print("=" * 70)
    print("ERROR: Git commit signing is not properly configured")
    print("=" * 70)
    print(f"\n{message}\n")
    print("This repository requires all commits to be signed.")
    print("\nTo configure Git commit signing (preferred):")
    print("  # If using the repo virtualenv")
    print("  .venv/bin/python -m scripts.devops.setup_git_signing")
    print("  # If the virtualenv is not available")
    print("  python3 -m scripts.devops.setup_git_signing")
    print("\nOr manually configure:")
    print("  git config --global gpg.format ssh")
    print("  git config --global user.signingkey ~/.ssh/id_ed25519_signing.pub")
    print("  git config --global commit.gpgsign true")
    print("\nSee: docs/automation/runbooks/fix-unsigned-commits-in-pr.md")
    print("=" * 70)
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
