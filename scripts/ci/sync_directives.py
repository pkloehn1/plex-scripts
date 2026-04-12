"""Sync AI directive files between repositories.

Reads ``.github/sync-directives.yml`` for the list of files, directory
patterns, and per-target exclusions, then copies from *source* to *target*
while honouring the exclusion list for the given target repository.
"""

from __future__ import annotations

import argparse
import filecmp
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from scripts.ci.merge_precommit_config import merge_precommit_config
from scripts.common.paths import normalize_path

_PRECOMMIT_CONFIG = ".pre-commit-config.yaml"

_GLOB_CHARS: frozenset[str] = frozenset({"*", "?", "["})


@dataclass(frozen=True)
class SyncResult:
    """Outcome of a directive sync operation."""

    copied: tuple[str, ...]
    skipped: tuple[str, ...]
    removed: tuple[str, ...]
    unchanged: tuple[str, ...]


def load_config(config_path: Path) -> dict[str, Any]:
    """Load and return the sync-directives YAML configuration."""
    with config_path.open(encoding="utf-8") as config_file:
        loaded = yaml.safe_load(config_file)

    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        msg = f"Invalid sync-directives config at {config_path}: expected a mapping, got {type(loaded).__name__}"
        raise ValueError(msg)

    return loaded


def _collect_glob_matches(
    glob_root: Path,
    pattern: str,
    rel_base: Path,
    seen: set[str],
) -> list[str]:
    """Expand a glob *pattern* under *glob_root*, returning paths relative to *rel_base*."""
    collected: list[str] = []
    for match in sorted(glob_root.glob(pattern)):
        if match.is_file():
            rel = normalize_path(str(match.relative_to(rel_base)))
            if rel not in seen:
                seen.add(rel)
                collected.append(rel)
    return collected


def resolve_files(source: Path, config: dict[str, Any]) -> list[str]:
    """Expand config entries into concrete relative paths that exist in *source*.

    Entries in ``files:`` may be literal paths or glob patterns (containing
    ``*``, ``?``, or ``[``).  Literal paths are included when the file exists;
    glob patterns are expanded via :py:meth:`pathlib.Path.glob`.

    A ``seen`` set prevents duplicates when the same file is matched by both
    a ``files:`` glob and a ``directories:`` pattern.
    """
    result: list[str] = []
    seen: set[str] = set()

    for file_path in config.get("files", []):
        if _GLOB_CHARS & set(file_path):
            result.extend(_collect_glob_matches(source, file_path, source, seen))
        elif (source / file_path).is_file():
            norm = normalize_path(file_path)
            if norm not in seen:
                seen.add(norm)
                result.append(file_path)

    for entry in config.get("directories", []):
        dir_path = source / entry["path"]
        if dir_path.is_dir():
            result.extend(_collect_glob_matches(dir_path, entry["pattern"], source, seen))

    return result


def get_excludes(config: dict[str, Any], target_repo: str) -> set[str]:
    """Return excluded file paths for *target_repo*."""
    raw: dict[str, list[str]] = config.get("exclude") or {}
    return set(raw.get(target_repo, []))


def _sync_precommit_config(
    src: Path,
    target: Path,
    dst: Path,
) -> str:
    """Merge or copy .pre-commit-config.yaml, returning 'copied' or 'unchanged'."""
    had_dst = dst.is_file()
    old_content = dst.read_bytes() if had_dst else b""
    merge_precommit_config(hub_config=src, target_dir=target, output=dst)
    if had_dst and dst.read_bytes() == old_content:
        return "unchanged"
    return "copied"


def _sync_one_file(src: Path, dst: Path) -> str:
    """Copy a single file, returning 'copied' or 'unchanged'."""
    if dst.is_file() and filecmp.cmp(src, dst, shallow=False):
        return "unchanged"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return "copied"


def _remove_stale_files(
    target: Path,
    config: dict[str, Any],
    source_set: set[str],
    excludes: set[str],
) -> list[str]:
    """Remove files in *target* that are no longer in *source_set*."""
    target_files = set(resolve_files(target, config))
    removed: list[str] = []
    for rel_path in sorted(target_files - source_set):
        if rel_path in excludes:
            continue
        victim = target / rel_path
        if victim.is_file():
            victim.unlink()
            removed.append(rel_path)
    return removed


def sync_files(
    *,
    source: Path,
    target: Path,
    config: dict[str, Any],
    target_repo: str,
) -> SyncResult:
    """Copy directive files from *source* to *target*, respecting exclusions.

    Files present in the target's scope but absent from the source are removed
    so that deletions propagate.  Files whose content already matches are left
    untouched and reported as *unchanged*.
    """
    source_files = resolve_files(source, config)
    excludes = get_excludes(config, target_repo)

    copied: list[str] = []
    skipped: list[str] = []
    unchanged: list[str] = []

    for rel_path in source_files:
        if rel_path in excludes:
            skipped.append(rel_path)
            continue

        src = source / rel_path
        if not src.is_file():
            continue

        dst = target / rel_path
        if rel_path == _PRECOMMIT_CONFIG:
            outcome = _sync_precommit_config(src, target, dst)
        else:
            outcome = _sync_one_file(src, dst)
        (unchanged if outcome == "unchanged" else copied).append(rel_path)

    removed = _remove_stale_files(target, config, set(source_files), excludes)

    return SyncResult(
        copied=tuple(copied),
        skipped=tuple(skipped),
        removed=tuple(removed),
        unchanged=tuple(unchanged),
    )


def _parse_args() -> argparse.Namespace:  # pragma: no cover
    parser = argparse.ArgumentParser(
        description="Sync AI directive files between repositories.",
    )
    parser.add_argument("--source", required=True, type=Path, help="Source repo root")
    parser.add_argument("--target", required=True, type=Path, help="Target repo root")
    parser.add_argument(
        "--target-repo",
        required=True,
        help="Target repository (owner/name)",
    )
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to sync-directives.yml",
    )
    return parser.parse_args()


def format_summary(result: SyncResult, target_repo: str) -> str:
    """Return a Markdown summary suitable for ``$GITHUB_STEP_SUMMARY``."""
    lines: list[str] = [f"## Sync → `{target_repo}`", ""]

    def _section(icon: str, label: str, items: tuple[str, ...]) -> None:
        lines.append(f"### {icon} {label} ({len(items)})")
        if items:
            for item in items:
                lines.append(f"- `{item}`")
        else:
            lines.append("_None._")
        lines.append("")

    _section("📋", "Copied", result.copied)
    _section("🗑️", "Removed", result.removed)
    _section("⏭️", "Skipped (excluded)", result.skipped)
    _section("✅", "Unchanged", result.unchanged)

    return "\n".join(lines)


def main() -> int:  # pragma: no cover
    """Entry point for ``python -m scripts.ci.sync_directives``."""
    args = _parse_args()
    config = load_config(args.config)
    result = sync_files(
        source=args.source,
        target=args.target,
        config=config,
        target_repo=args.target_repo,
    )

    summary = format_summary(result, args.target_repo)
    print(summary)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary_file:
            summary_file.write(summary + "\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
