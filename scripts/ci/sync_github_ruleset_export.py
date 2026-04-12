#!/usr/bin/env python3
"""Synchronize and manage GitHub ruleset configuration.

Modes of operation:

Export (default):
- Reads the current ruleset configuration from GitHub.
- Updates a local JSONC export file to match.
- Export is one-way: it never writes configuration back to GitHub.

Validate (--validate-contexts):
- Compares declared required-contexts YAML against the live ruleset.
- Reports drift (added, removed, or mismatched integration IDs).

Apply (--apply-contexts):
- Pushes declared required contexts to the live ruleset via the GitHub API.
- Dry-run by default; use --confirm to execute.

Requirements:
- GitHub CLI (``gh``) must be available.
- Authentication must permit reading (and, for apply, writing) repo rulesets.

Idempotency:
- If the normalized remote ruleset matches the existing export, the file is not
    modified.
"""

from __future__ import annotations

import argparse
import copy
import dataclasses
import json
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from scripts.common.json_utils import parse_json_object
from scripts.common.paths import repo_root as _repo_root

_VOLATILE_KEYS: frozenset[str] = frozenset(
    {
        "node_id",
        "created_at",
        "updated_at",
        "current_user_can_bypass",
        "_links",
    }
)


@dataclass(frozen=True)
class DiffSummary:
    added_required_contexts: set[str]
    removed_required_contexts: set[str]
    mismatched_integration_ids: dict[str, tuple[int, int]] = dataclasses.field(default_factory=dict)


def _run(args: list[str]) -> str:  # pragma: no cover
    result = subprocess.run(
        args,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout


def fetch_ruleset_json(*, repo: str, ruleset_id: int) -> dict[str, Any]:
    """Fetch a ruleset JSON payload via `gh api`.

    Args:
        repo: GitHub repo in `owner/name` form.
        ruleset_id: Numeric ruleset ID.

    Returns:
        Parsed JSON object.
    """
    raw = _run(["gh", "api", f"/repos/{repo}/rulesets/{ruleset_id}"])
    return parse_json_object(raw)


def normalize_ruleset(ruleset: dict[str, Any]) -> dict[str, Any]:
    """Normalize a ruleset payload for stable, reviewable export.

    Removes volatile metadata that is not useful for documentation diffs.
    """
    normalized = {key: val for key, val in ruleset.items() if key not in _VOLATILE_KEYS}
    return normalized


def extract_json_object(jsonc_text: str) -> dict[str, Any]:
    """Extract the first JSON object found in a JSONC file."""
    start = jsonc_text.find("{")
    if start == -1:
        raise ValueError("No JSON object found")

    try:
        return parse_json_object(jsonc_text[start:])
    except (ValueError, TypeError) as exc:
        raise ValueError("Failed to parse JSON object") from exc


def _find_required_status_checks(ruleset: dict[str, Any]) -> list[dict[str, Any]]:
    rules = ruleset.get("rules")
    if not isinstance(rules, list):
        return []

    out: list[dict[str, Any]] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        if rule.get("type") != "required_status_checks":
            continue
        params = rule.get("parameters")
        if not isinstance(params, dict):
            continue
        checks = params.get("required_status_checks")
        if isinstance(checks, list):
            out.extend([chk for chk in checks if isinstance(chk, dict)])
    return out


def _contexts_from_required_checks(ruleset: dict[str, Any]) -> set[str]:
    contexts: set[str] = set()
    for check in _find_required_status_checks(ruleset):
        context = check.get("context")
        if isinstance(context, str) and context.strip():
            contexts.add(context.strip())
    return contexts


def diff_summary(before: dict[str, Any], after: dict[str, Any]) -> DiffSummary:
    before_ctx = _contexts_from_required_checks(before)
    after_ctx = _contexts_from_required_checks(after)
    return DiffSummary(
        added_required_contexts=after_ctx - before_ctx,
        removed_required_contexts=before_ctx - after_ctx,
    )


def render_ruleset_jsonc(
    *,
    repo: str,
    ruleset_name: str,
    normalized_ruleset: dict[str, Any],
    exported_on: date,
) -> str:
    header = "\n".join(
        [
            "// GitHub Ruleset export (documented)",
            f"// Repo: {repo}",
            f"// Ruleset: {ruleset_name}",
            "// Target: default branch (~DEFAULT_BRANCH)",
            f"// Exported: {exported_on.isoformat()}",
            "// Notes:",
            "// - This is a curated export for documentation and diff review.",
            "// - Volatile metadata (node_id, timestamps, links, current_user_can_bypass) is intentionally omitted.",
            "// - This tool is one-way: it never writes ruleset configuration back to GitHub.",
            "",
        ]
    )

    payload = json.dumps(normalized_ruleset, indent=2)
    return header + payload + "\n"


def write_ruleset_jsonc_if_changed(
    *,
    path: Path,
    repo: str,
    ruleset_name: str,
    normalized_ruleset: dict[str, Any],
) -> bool:
    """Write JSONC export if content differs.

    Returns:
        True if the file was created/updated; False if unchanged.
    """
    existing: dict[str, Any] | None = None
    if path.exists():
        existing_text = path.read_text(encoding="utf-8")
        existing = extract_json_object(existing_text)

    if existing == normalized_ruleset:
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = render_ruleset_jsonc(
        repo=repo,
        ruleset_name=ruleset_name,
        normalized_ruleset=normalized_ruleset,
        exported_on=date.today(),
    )
    path.write_text(rendered, encoding="utf-8")
    return True


def _run_with_input(args: list[str], stdin_data: str) -> str:  # pragma: no cover
    result = subprocess.run(
        args,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        input=stdin_data,
    )
    return result.stdout


# ---------------------------------------------------------------------------
# Declarative required-contexts management
# ---------------------------------------------------------------------------


def load_required_contexts(path: Path) -> list[dict[str, Any]]:
    """Load and validate a required-contexts YAML file.

    Returns a list of ``{context: str, integration_id: int}`` dicts.
    """
    with path.open(encoding="utf-8") as yml:
        data = yaml.safe_load(yml)

    if data is None:
        return []

    if not isinstance(data, list):
        raise ValueError(f"{path}: must be a YAML list of context entries")

    for idx, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise ValueError(f"{path}[{idx}]: entry must be a mapping, got {type(entry).__name__}")
        if "context" not in entry:
            raise ValueError(f"{path}[{idx}]: missing required key 'context'")
        if not isinstance(entry["context"], str):
            raise ValueError(f"{path}[{idx}]: 'context' must be a string")
        if "integration_id" not in entry:
            raise ValueError(f"{path}[{idx}]: missing required key 'integration_id'")
        if not isinstance(entry["integration_id"], int):
            raise ValueError(f"{path}[{idx}]: 'integration_id' must be an integer")

    return data


def validate_contexts(
    declared: list[dict[str, Any]],
    live_ruleset: dict[str, Any],
) -> DiffSummary:
    """Compare declared contexts against the live ruleset.

    Returns a ``DiffSummary`` where *added* means in declared but not live,
    *removed* means in live but not declared, and *mismatched_integration_ids*
    maps context names to ``(declared_id, live_id)`` when they differ.
    """
    declared_names = {entry["context"] for entry in declared}
    live_names = _contexts_from_required_checks(live_ruleset)

    # Build integration_id lookup for live checks
    live_ids: dict[str, int] = {}
    for check in _find_required_status_checks(live_ruleset):
        ctx = check.get("context")
        iid = check.get("integration_id")
        if isinstance(ctx, str) and isinstance(iid, int):
            live_ids[ctx] = iid

    mismatched: dict[str, tuple[int, int]] = {}
    common = declared_names & live_names
    for entry in declared:
        name = entry["context"]
        if name in common and name in live_ids:
            declared_id = entry["integration_id"]
            if declared_id != live_ids[name]:
                mismatched[name] = (declared_id, live_ids[name])

    return DiffSummary(
        added_required_contexts=declared_names - live_names,
        removed_required_contexts=live_names - declared_names,
        mismatched_integration_ids=mismatched,
    )


def build_status_checks_patch(
    contexts: list[dict[str, Any]],
    live_ruleset: dict[str, Any],
) -> dict[str, Any]:
    """Build a full ruleset payload with status checks replaced by *contexts*.

    Uses deep-copy to avoid mutating *live_ruleset*.
    """
    patched = copy.deepcopy(live_ruleset)
    rules = patched.get("rules")
    if not isinstance(rules, list):
        raise ValueError("No required_status_checks rule found in live ruleset")

    for rule in rules:
        if not isinstance(rule, dict):
            continue
        if rule.get("type") != "required_status_checks":
            continue
        params = rule.get("parameters")
        if isinstance(params, dict):
            params["required_status_checks"] = contexts
            return patched

    raise ValueError("No required_status_checks rule found in live ruleset")


def apply_contexts(
    *,
    repo: str,
    ruleset_id: int,
    patch: dict[str, Any],
    dry_run: bool = True,
) -> str:
    """Apply a patched ruleset to GitHub.

    When *dry_run* is True, returns a message without calling the API.
    """
    if dry_run:
        return f"Dry-run: would PUT {len(patch.get('rules', []))} rules to {repo} ruleset {ruleset_id}"

    payload = json.dumps(patch)
    _run_with_input(
        ["gh", "api", "-X", "PUT", f"/repos/{repo}/rulesets/{ruleset_id}", "--input", "-"],
        stdin_data=payload,
    )
    return f"Applied required contexts to {repo} ruleset {ruleset_id}"


def _format_diff(diff: DiffSummary) -> str:
    """Format a DiffSummary as a human-readable string."""
    lines: list[str] = []
    if diff.added_required_contexts:
        lines.append(f"  + {', '.join(sorted(diff.added_required_contexts))}")
    if diff.removed_required_contexts:
        lines.append(f"  - {', '.join(sorted(diff.removed_required_contexts))}")
    for name in sorted(diff.mismatched_integration_ids):
        declared_id, live_id = diff.mismatched_integration_ids[name]
        lines.append(f"  ~ {name}: integration_id {declared_id} (declared) != {live_id} (live)")
    return "\n".join(lines)


def run_validate_contexts(
    *,
    repo: str,
    ruleset_id: int,
    contexts_file: Path,
) -> int:
    """Validate declared contexts against the live ruleset. Returns exit code."""
    declared = load_required_contexts(contexts_file)
    live = fetch_ruleset_json(repo=repo, ruleset_id=ruleset_id)
    diff = validate_contexts(declared, live)

    has_drift = diff.added_required_contexts or diff.removed_required_contexts or diff.mismatched_integration_ids
    if not has_drift:
        print("Required contexts match the live ruleset.")
        return 0

    print("Required contexts drift detected:")
    print(_format_diff(diff))
    return 2


def run_apply_contexts(
    *,
    repo: str,
    ruleset_id: int,
    contexts_file: Path,
    dry_run: bool = True,
) -> None:
    """Apply declared contexts to the live ruleset."""
    declared = load_required_contexts(contexts_file)
    live = fetch_ruleset_json(repo=repo, ruleset_id=ruleset_id)
    diff = validate_contexts(declared, live)

    has_drift = diff.added_required_contexts or diff.removed_required_contexts or diff.mismatched_integration_ids
    if not has_drift:
        print("Required contexts already match. Nothing to apply.")
        return

    print("Changes:")
    print(_format_diff(diff))

    patch = build_status_checks_patch(declared, live)
    result = apply_contexts(repo=repo, ruleset_id=ruleset_id, patch=patch, dry_run=dry_run)
    print(result)


def _parse_args() -> argparse.Namespace:  # pragma: no cover
    parser = argparse.ArgumentParser(description="Sync a local JSONC ruleset export from the live GitHub ruleset.")
    parser.add_argument("--repo", required=True, help="GitHub repo: owner/name")
    parser.add_argument("--ruleset-id", required=True, type=int, help="Ruleset ID")
    parser.add_argument(
        "--ruleset-name",
        default="main",
        help="Ruleset name for documentation header (default: main)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the export file would change (no write).",
    )
    parser.add_argument(
        "--validate-contexts",
        action="store_true",
        help="Validate declared contexts against the live ruleset.",
    )
    parser.add_argument(
        "--apply-contexts",
        action="store_true",
        help="Apply declared contexts to the live ruleset (dry-run by default).",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Actually apply changes (disables dry-run for --apply-contexts).",
    )
    parser.add_argument(
        "--contexts-file",
        default=None,
        help="Path to required-contexts.yml (default: docs/ci/github-rulesets/required-contexts.yml)",
    )
    return parser.parse_args()


def main() -> int:  # pragma: no cover
    args = _parse_args()
    repo_root = _repo_root()

    contexts_file = (
        Path(args.contexts_file) if args.contexts_file else repo_root / "docs/ci/github-rulesets/required-contexts.yml"
    )

    if args.validate_contexts:
        return run_validate_contexts(
            repo=args.repo,
            ruleset_id=args.ruleset_id,
            contexts_file=contexts_file,
        )

    if args.apply_contexts:
        run_apply_contexts(
            repo=args.repo,
            ruleset_id=args.ruleset_id,
            contexts_file=contexts_file,
            dry_run=not args.confirm,
        )
        return 0

    output_path = repo_root / "docs/ci/github-rulesets/main-ruleset.jsonc"

    remote_raw = fetch_ruleset_json(repo=args.repo, ruleset_id=args.ruleset_id)
    remote = normalize_ruleset(remote_raw)

    existing: dict[str, Any] | None = None
    if output_path.exists():
        existing = extract_json_object(output_path.read_text(encoding="utf-8"))

    summary = diff_summary(existing or {}, remote)

    if args.check:
        if existing == remote:
            print("Ruleset export is up to date.")
            return 0

        print("Ruleset export differs from remote.")
        if summary.added_required_contexts or summary.removed_required_contexts:
            print(
                "Required contexts:"
                f"\n  added: {sorted(summary.added_required_contexts)}"
                f"\n  removed: {sorted(summary.removed_required_contexts)}"
            )
        return 2

    changed = write_ruleset_jsonc_if_changed(
        path=output_path,
        repo=args.repo,
        ruleset_name=args.ruleset_name,
        normalized_ruleset=remote,
    )

    if changed:
        print(f"Updated ruleset export: {output_path}")
        if summary.added_required_contexts or summary.removed_required_contexts:
            print(
                "Required contexts:"
                f"\n  added: {sorted(summary.added_required_contexts)}"
                f"\n  removed: {sorted(summary.removed_required_contexts)}"
            )
        return 0

    print("Ruleset export is up to date.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
