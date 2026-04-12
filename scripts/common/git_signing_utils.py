from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def is_windows() -> bool:
    """Return True when running on Windows."""
    return sys.platform == "win32"


def git_config_value(key: str) -> str | None:
    """Fetch a git config value or None."""
    result = subprocess.run(
        ["git", "config", "--get", key],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def find_signing_key_path(user_signingkey: str | None) -> Path | None:
    """Resolve signing key path with tilde expansion and common fallbacks.

    On Windows, fallbacks prefer public keys (.pub) because the Windows SSH
    agent performs signing via the agent protocol.

    On Linux, fallbacks prefer private keys because ``ssh-keygen -Y sign``
    can sign directly with a passphrase-free private key — no agent required.
    """
    if user_signingkey:
        candidate = Path(user_signingkey).expanduser()
        if candidate.exists():
            return candidate
    ssh_dir = Path.home() / ".ssh"
    if is_windows():
        # Windows: public keys (SSH agent handles signing)
        candidates = [
            ssh_dir / "id_ed25519_signing.pub",
            ssh_dir / "id_ed25519.pub",
            ssh_dir / "id_rsa_signing.pub",
        ]
    else:
        # Linux: private keys first (direct signing, no agent needed)
        candidates = [
            ssh_dir / "id_ed25519_signing",
            ssh_dir / "id_ed25519_signing.pub",
            ssh_dir / "id_ed25519",
            ssh_dir / "id_ed25519.pub",
            ssh_dir / "id_rsa_signing",
            ssh_dir / "id_rsa_signing.pub",
        ]
    for key_path in candidates:
        if key_path.exists():
            return key_path
    return None
