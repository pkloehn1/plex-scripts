#!/usr/bin/env python3
"""Cross-platform wrapper to run the local Super-Linter script from pre-commit."""

from __future__ import annotations

import subprocess
import sys

from scripts.common.paths import repo_root


def main() -> None:
    """Run the local Super-Linter bash script."""
    script_path = repo_root() / "scripts" / "local_super_linter.sh"
    cmd = ["bash", str(script_path)]

    print(f"Running Super-Linter via {cmd[0]}...")

    try:
        result = subprocess.run(cmd, check=False)
        sys.exit(result.returncode)
    except OSError as exc:
        print(f"Error running Super-Linter: {exc}")
        sys.exit(1)


if __name__ == "__main__":  # pragma: no cover
    main()
