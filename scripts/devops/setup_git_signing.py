#!/usr/bin/env python3
"""Setup Git commit signing for cross-platform use (Windows and Linux).

This script automates the configuration of Git commit signing using SSH keys,
ensuring consistent setup across Windows and Linux environments.

Usage:
    .venv/bin/python -m scripts.devops.setup_git_signing [--check-only] [--key-path PATH] [--email EMAIL] [--passphrase PASSPHRASE | --no-passphrase]
    python3 -m scripts.devops.setup_git_signing [--check-only] [--key-path PATH] [--email EMAIL] [--passphrase PASSPHRASE | --no-passphrase]

Security note:
    Keys are generated with a passphrase by default. Use --no-passphrase explicitly
    to generate an unprotected key for automation scenarios.

Options:
    --check-only: Only verify current configuration without making changes
    --key-path PATH: Path to existing SSH public key (default: auto-detect or create)
    --email EMAIL: GitHub email address (default: detect from git config or gh CLI)
    --force: Overwrite existing configuration
    --passphrase PASSPHRASE: Optional passphrase when generating a new key
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from scripts.common.git_signing_utils import find_signing_key_path, git_config_value, is_windows

# Git config keys (constants to avoid duplication)
GIT_CONFIG_COMMIT_GPGSIGN = "commit.gpgsign"
GIT_CONFIG_GPG_FORMAT = "gpg.format"
GIT_CONFIG_USER_SIGNINGKEY = "user.signingkey"
GIT_CONFIG_GPG_SSH_ALLOWED_SIGNERS = "gpg.ssh.allowedSignersFile"


def get_ssh_dir() -> Path:
    """Get the SSH directory path (cross-platform)."""
    return Path.home() / ".ssh"


def find_existing_signing_key() -> Path | None:
    """Find an existing SSH signing key."""
    return find_signing_key_path(None)


def _split_key_paths(key_path: Path) -> tuple[Path, Path]:
    """Return (private_key, public_key) for a provided key_path."""
    if key_path.suffix == ".pub":
        return key_path.with_suffix(""), key_path
    return key_path, key_path.with_suffix(".pub")


def _looks_like_private_key(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return "PRIVATE KEY" in text


def _regenerate_public_key(private_key: Path, public_key: Path) -> bool:
    print("[INFO] Private key exists, regenerating public key...")
    try:
        result = subprocess.run(
            ["ssh-keygen", "-y", "-f", str(private_key)],
            capture_output=True,
            text=True,
            check=True,
        )
        public_key.write_text(result.stdout.strip() + "\n")
        print(f"[OK] Regenerated public key: {public_key}")
        return True
    except subprocess.CalledProcessError as err:
        print(f"[FAIL] Failed to regenerate public key: {str(err.stderr) if err.stderr else str(err)}")
        return False
    except FileNotFoundError:
        print("[FAIL] ssh-keygen not found. Please install OpenSSH.")
        return False


def _generate_signing_key(private_key: Path, *, passphrase: str) -> bool:
    print(f"[INFO] Creating new SSH signing key: {private_key}")
    try:
        subprocess.run(
            [
                "ssh-keygen",
                "-t",
                "ed25519",
                "-C",
                "github-commit-signing",
                "-f",
                str(private_key),
                "-N",
                passphrase,
            ],
            check=True,
            capture_output=True,
        )
        print(f"[OK] Created signing key: {private_key.with_suffix('.pub')}")
        return True
    except subprocess.CalledProcessError as err:
        print(f"[FAIL] Failed to create key: {str(err.stderr) if err.stderr else str(err)}")
        return False
    except FileNotFoundError:
        print("[FAIL] ssh-keygen not found. Please install OpenSSH.")
        return False


def create_signing_key(key_path: Path, *, passphrase: str) -> bool:
    """Create a new SSH signing key."""
    if key_path.exists():
        print(f"[INFO] Key already exists: {key_path}")
        return True

    private_key, public_key = _split_key_paths(key_path)

    if private_key.exists() and not public_key.exists():
        return _regenerate_public_key(private_key, public_key)

    return _generate_signing_key(private_key, passphrase=passphrase)


def _email_from_git_config() -> str | None:
    try:
        email_cfg = git_config_value("user.email")
    except Exception:
        return None
    if not email_cfg:
        return None
    if "@users.noreply.github.com" in email_cfg or "@" in email_cfg:
        return email_cfg
    return None


def _email_from_gh_payload(user_data: dict[str, Any]) -> str | None:
    email = user_data.get("email")
    if isinstance(email, str) and email:
        return email
    login = user_data.get("login")
    if isinstance(login, str) and login:
        return f"{login}@users.noreply.github.com"
    return None


def _email_from_gh_cli() -> str | None:
    try:
        result = subprocess.run(
            ["gh", "api", "/user"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    try:
        import json

        user_data = json.loads(result.stdout)
    except Exception:
        return None
    return _email_from_gh_payload(user_data) if isinstance(user_data, dict) else None


def get_github_email() -> str | None:
    """Get GitHub email from git config or gh CLI."""
    email = _email_from_git_config()
    if email:
        return email
    return _email_from_gh_cli()


def check_git_config() -> dict[str, str | None]:
    """Check current Git signing configuration."""
    config = {}
    for key in [
        GIT_CONFIG_COMMIT_GPGSIGN,
        GIT_CONFIG_GPG_FORMAT,
        GIT_CONFIG_USER_SIGNINGKEY,
        GIT_CONFIG_GPG_SSH_ALLOWED_SIGNERS,
    ]:
        try:
            config[key] = git_config_value(key)
        except Exception:
            config[key] = None
    return config


def _resolve_signing_key(key_path: Path) -> Path | None:
    """Return the OS-appropriate signing key path, or None on error.

    Windows: public key (.pub) — the Windows SSH agent performs signing.
    Linux:   private key — ``ssh-keygen -Y sign`` signs directly (no agent).
    """
    private_key, public_key = _split_key_paths(key_path)
    if is_windows():
        if not public_key.exists():
            print(f"[FAIL] Public key not found: {public_key}")
            return None
        if _looks_like_private_key(public_key):
            print(f"[FAIL] Public key path appears to contain private key material: {public_key}")
            return None
        return public_key
    # Linux: use the private key for agent-free signing
    if not private_key.exists():
        print(f"[FAIL] Private key not found: {private_key}")
        return None
    return private_key


def _configure_git(key_path: Path) -> bool:
    """Configure git signing keys and settings."""
    signing_key = _resolve_signing_key(key_path)
    if signing_key is None:
        return False
    try:
        subprocess.run(["git", "config", "--global", GIT_CONFIG_GPG_FORMAT, "ssh"], check=True)
        subprocess.run(
            ["git", "config", "--global", GIT_CONFIG_USER_SIGNINGKEY, str(signing_key)],
            check=True,
        )
        subprocess.run(["git", "config", "--global", GIT_CONFIG_COMMIT_GPGSIGN, "true"], check=True)
        print("[OK] Configured Git for SSH signing")
        return True
    except subprocess.CalledProcessError as err:
        print(f"[FAIL] Failed to configure Git: {err}")
        return False


def _configure_allowed_signers(key_path: Path, email: str | None) -> None:
    """Configure allowed signers file when email is provided."""
    if not email:
        return
    _private_key, public_key = _split_key_paths(key_path)
    if not public_key.exists():
        print(f"[WARN] Cannot configure allowed signers; public key missing: {public_key}")
        return

    allowed_signers = Path.home() / ".config" / "git" / "allowed_signers"
    allowed_signers.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(public_key) as file_handle:
            key_line = file_handle.read().strip()
            parts = key_line.split()
            if len(parts) < 2:
                print(f"[WARN] Signing key appears malformed (expected at least 2 fields): {public_key}")
                return

            key_type = parts[0]
            key_data = parts[1]
            signers_line = f"{email} {key_type} {key_data} signed-by-git\n"
            allowed_signers.write_text(signers_line)
            subprocess.run(
                ["git", "config", "--global", GIT_CONFIG_GPG_SSH_ALLOWED_SIGNERS, str(allowed_signers)],
                check=True,
            )
            print(f"[OK] Configured allowed signers file: {allowed_signers}")
    except Exception as err:
        print(f"[WARN] Could not configure allowed signers file: {err}")


def configure_git_signing(
    *,
    key_path: Path,
    email: str | None = None,
    force: bool = False,
) -> bool:
    """Configure Git for SSH commit signing."""
    config = check_git_config()

    # Check if already configured
    if (
        config.get(GIT_CONFIG_COMMIT_GPGSIGN) == "true"
        and config.get(GIT_CONFIG_GPG_FORMAT) == "ssh"
        and config.get(GIT_CONFIG_USER_SIGNINGKEY)
        and not force
    ):
        existing_key = config.get(GIT_CONFIG_USER_SIGNINGKEY)
        if existing_key and Path(existing_key).expanduser().exists():
            print("[INFO] Git signing already configured")
            print(f"  {GIT_CONFIG_COMMIT_GPGSIGN}: {config.get(GIT_CONFIG_COMMIT_GPGSIGN)}")
            print(f"  {GIT_CONFIG_GPG_FORMAT}: {config.get(GIT_CONFIG_GPG_FORMAT)}")
            print(f"  {GIT_CONFIG_USER_SIGNINGKEY}: {existing_key}")
            return True

    if not _configure_git(key_path):
        return False

    _private_key, public_key = _split_key_paths(key_path)
    _configure_allowed_signers(public_key, email)

    return True


def _verify_key_exists(key_path: Path) -> bool:
    """Verify signing key file exists."""
    if not key_path.exists():
        print(f"[FAIL] Signing key not found: {key_path}")
        return False
    print(f"[OK] Signing key exists: {key_path}")
    return True


def _verify_git_config(config: Mapping[str, str | None]) -> bool:
    """Verify Git signing configuration values."""
    if config.get(GIT_CONFIG_COMMIT_GPGSIGN) != "true":
        print(f"[FAIL] {GIT_CONFIG_COMMIT_GPGSIGN} is not 'true'")
        return False
    print(f"[OK] {GIT_CONFIG_COMMIT_GPGSIGN} is 'true'")

    if config.get(GIT_CONFIG_GPG_FORMAT) != "ssh":
        print(f"[FAIL] {GIT_CONFIG_GPG_FORMAT} is not 'ssh'")
        return False
    print(f"[OK] {GIT_CONFIG_GPG_FORMAT} is 'ssh'")

    signingkey = config.get(GIT_CONFIG_USER_SIGNINGKEY)
    if not signingkey:
        print(f"[FAIL] {GIT_CONFIG_USER_SIGNINGKEY} is not set")
        return False
    print(f"[OK] {GIT_CONFIG_USER_SIGNINGKEY} is set: {signingkey}")
    return True


def _verify_signature_capability() -> None:
    """Verify Git can attempt signature verification."""
    try:
        result = subprocess.run(
            ["git", "log", "--show-signature", "-n", "1"],
            capture_output=True,
            text=True,
            check=False,
        )
        if "Good signature" in result.stdout or "No signature" in result.stdout:
            print("[OK] Git can verify signatures")
    except Exception:
        # Best-effort fallback when git/gh email lookup fails
        pass


def verify_setup(key_path: Path) -> bool:
    """Verify the signing setup is working."""
    print("\n[INFO] Verifying setup...")
    private_key, public_key = _split_key_paths(key_path)
    verify_key = public_key if is_windows() else private_key

    if not _verify_key_exists(verify_key):
        return False

    config = check_git_config()
    if not _verify_git_config(config):
        return False

    _verify_signature_capability()
    return True


def _print_ssh_add_instruction(key_path: Path) -> None:
    """Print SSH agent add instruction."""
    private_key, _public_key = _split_key_paths(key_path)
    print("1. Add the signing key to your SSH agent:")
    print(f"   ssh-add {private_key}")


def _print_github_registration_instruction(key_path: Path) -> None:
    """Print GitHub key registration instructions."""
    _private_key, public_key = _split_key_paths(key_path)
    print("\n2. Register the public key on GitHub:")
    print("   - Go to: https://github.com/settings/keys")
    print("   - Click 'New SSH key'")
    print("   - Key type: Signing key")
    print("   - Paste the contents of:")
    print(f"     {public_key}")


def _print_display_key_instruction(key_path: Path) -> None:
    """Print instructions to display the public key."""
    _private_key, public_key = _split_key_paths(key_path)
    print("\n3. Display the public key:")
    print(f"   cat {public_key}")
    if sys.platform == "win32":
        print("   # Or on Windows:")
        print(f"   Get-Content {public_key}")


def print_next_steps(key_path: Path) -> None:
    """Print instructions for next steps."""
    print("\n[INFO] Next steps:")
    _print_ssh_add_instruction(key_path)
    _print_github_registration_instruction(key_path)
    _print_display_key_instruction(key_path)


def main() -> int:
    """Main entry point."""
    args = _parse_args()
    key_path = _resolve_key_path(args.key_path)

    if _handle_check_only(args.check_only, key_path):
        return 0

    existing_key = key_path.exists()
    passphrase: str | None = None
    if not existing_key:
        passphrase = _resolve_passphrase(args)
        if passphrase is None:
            return 1

    email = _resolve_email(args.email)
    if not _ensure_signing_key(key_path, passphrase=passphrase):
        return 1

    if not configure_git_signing(key_path=key_path, email=email, force=args.force):
        return 1
    if not verify_setup(key_path):
        return 1

    print_next_steps(key_path)
    print("\n[OK] Git signing setup complete!")
    return 0


def _parse_args() -> argparse.Namespace:  # pragma: no cover
    parser = argparse.ArgumentParser(
        description="Setup Git commit signing for cross-platform use",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only verify current configuration without making changes",
    )
    parser.add_argument(
        "--key-path",
        type=Path,
        help="Path to SSH public key (default: auto-detect or create)",
    )
    parser.add_argument(
        "--email",
        help="GitHub email address (default: detect from git config or gh CLI)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing configuration",
    )
    passphrase_group = parser.add_mutually_exclusive_group()
    passphrase_group.add_argument(
        "--passphrase",
        default=None,
        help="Passphrase to use when generating a new key (default: required)",
    )
    passphrase_group.add_argument(
        "--no-passphrase",
        action="store_true",
        help="Allow generating a key without a passphrase (automation only)",
    )
    return parser.parse_args()


def _resolve_key_path(arg_key_path: Path | None) -> Path:
    if arg_key_path:
        return Path(arg_key_path).expanduser().resolve()
    existing = find_existing_signing_key()
    if existing:
        return existing
    return get_ssh_dir() / "id_ed25519_signing.pub"


def _handle_check_only(check_only: bool, key_path: Path) -> bool:
    if not check_only:
        return False
    config = check_git_config()
    print("Current Git signing configuration:")
    for key, value in config.items():
        print(f"  {key}: {value or '(not set)'}")
    key_status = "exists" if key_path.exists() else "not found"
    print(f"\nSigning key {key_status}: {key_path}")
    return True


def _resolve_email(cli_email: str | None) -> str | None:
    email = cli_email or get_github_email()
    if not email:
        print("[WARN] Could not determine GitHub email. Some features may be limited.")
        print("       Use --email to specify your GitHub email address.")
    return email


def _ensure_signing_key(key_path: Path, *, passphrase: str | None) -> bool:
    if key_path.exists():
        return True
    if passphrase is None:
        print("[FAIL] Passphrase is required to generate a new signing key.")
        return False
    return create_signing_key(key_path, passphrase=passphrase)


def _resolve_passphrase(args: argparse.Namespace) -> str | None:
    if args.no_passphrase:
        return ""
    if args.passphrase is not None:
        passphrase: str = args.passphrase
        return passphrase
    print(
        "[FAIL] Passphrase is required unless --no-passphrase is specified "
        "to intentionally generate an unprotected key."
    )
    return None


if __name__ == "__main__":
    raise SystemExit(main())  # pragma: no cover
