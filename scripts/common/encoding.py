from __future__ import annotations

import sys


def ensure_utf8_stdio() -> None:
    """Ensure stdout/stderr use UTF-8 (primarily for Windows)."""
    if sys.platform != "win32":
        return
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
