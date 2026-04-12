"""Parse target repositories from sync-directives config.

Reads the ``targets`` key from a sync-directives YAML file and prints the
list as a JSON array to stdout, suitable for consumption by GitHub Actions
matrix strategies.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts.ci.sync_directives import load_config


def main(config_path: Path) -> None:
    """Load *config_path* and print the targets list as JSON."""
    config = load_config(config_path)
    targets = config.get("targets") or []
    print(json.dumps(targets))


if __name__ == "__main__":  # pragma: no cover
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".github/sync-directives.yml")
    main(path)
