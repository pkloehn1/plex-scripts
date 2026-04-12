"""Validate a merged pre-commit config file after hub-spoke sync.

Called by the ``run-sync-directives`` composite action to catch bad merges
before a spoke PR is created.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml


def validate_precommit_config(config_path: Path) -> int:
    """Return 0 if *config_path* is a valid pre-commit config, 1 otherwise.

    If the file does not exist, returns 0 (nothing to validate).
    """
    if not config_path.is_file():
        return 0

    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    if not isinstance(data, dict) or "repos" not in data:
        print(
            f"ERROR: merged config missing repos key: {config_path}",
            file=sys.stderr,
        )
        return 1

    print(f"Validated: {len(data['repos'])} repo entries")
    return 0


def _parse_args() -> argparse.Namespace:  # pragma: no cover
    parser = argparse.ArgumentParser(
        description="Validate a merged pre-commit config file.",
    )
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to .pre-commit-config.yaml",
    )
    return parser.parse_args()


def main() -> int:  # pragma: no cover
    """Entry point for ``python -m scripts.ci.validate_precommit_config``."""
    args = _parse_args()
    return validate_precommit_config(args.config)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
