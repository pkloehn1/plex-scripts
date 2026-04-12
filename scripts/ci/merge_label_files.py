"""Merge hub and spoke label YAML files into a single file for labeler sync."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from scripts.common.paths import repo_root


def merge_label_files(
    hub_path: Path,
    spoke_path: Path,
    output_path: Path,
) -> int:
    """Load hub and optional spoke label files, merge, and write output.

    Returns the total number of labels written.
    """
    with hub_path.open(encoding="utf-8") as yml:
        hub: list[dict[str, str]] = yaml.safe_load(yml) or []

    spoke: list[dict[str, str]] = []
    if spoke_path.exists():
        with spoke_path.open(encoding="utf-8") as yml:
            spoke = yaml.safe_load(yml) or []

    merged = hub + spoke

    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for label in merged:
        name = label.get("name", "")
        source = "spoke" if label in spoke else "hub"
        if name in seen:
            duplicates.append(f"{name!r} (in {seen[name]} and {source})")
        else:
            seen[name] = source
    if duplicates:
        msg = "Duplicate label names found:\n" + "\n".join(f"  - {dup}" for dup in duplicates)
        raise ValueError(msg)

    with output_path.open("w", encoding="utf-8") as out:
        yaml.safe_dump(
            merged,
            out,
            default_flow_style=False,
            sort_keys=False,
            explicit_start=True,
            explicit_end=True,
        )

    return len(merged)


def main() -> int:
    """Entry point for CI workflow usage."""
    github_dir = repo_root() / ".github"
    hub_path = github_dir / "labels-hub.yml"
    spoke_path = github_dir / "labels-spoke.yml"
    output_path = github_dir / "labels-merged.yml"

    count = merge_label_files(hub_path, spoke_path, output_path)
    print(f"Merged {count} labels")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
