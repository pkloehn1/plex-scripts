from __future__ import annotations

import os
import stat
from pathlib import Path


def ensure_executable(path: Path) -> None:
    """Ensure a path is executable on POSIX systems."""
    if os.name == "nt":
        return
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
