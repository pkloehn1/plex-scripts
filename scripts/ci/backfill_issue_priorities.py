#!/usr/bin/env python3
"""Backfill priority labels on open issues using deterministic rules.

Applies the three-input priority logic from the priority decision
framework document using label-based signals only:

1. Issue type (from title prefix, ``type/*`` labels, body keywords)
2. Service criticality tier (from ``service/*`` labels only — the AI
    agent additionally parses title scope and body content)
3. Blast radius (from ``service/*``, ``stack/*``, ``system/*`` label counts)

Dry-run by default; ``--apply`` adds labels via ``scripts.github.issue_upsert``.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from collections.abc import Callable

from scripts.ci.keyword_labeler import conventional_type_from_title
from scripts.github.gh_cli import (
    ActionableArgumentParser,
    GhRunner,
    SubprocessGhRunner,
    current_repo,
    run_actionable_main,
)
from scripts.github.issue_upsert import upsert_issue
from scripts.github.list_issues import list_issues

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PRIORITY_LABELS: frozenset[str] = frozenset({"P0-critical", "P1-high", "P2-medium", "P3-low"})

_PRIORITY_RANK: dict[str, int] = {
    "P0-critical": 0,
    "P1-high": 1,
    "P2-medium": 2,
    "P3-low": 3,
}

_SERVICE_TIERS: dict[str, int] = {
    "service/traefik": 0,
    "service/socket-proxy": 0,
    "service/authentik": 0,
    "service/authentik-postgres": 0,
    "service/gravitee-gateway": 1,
    "service/gravitee-management-api": 1,
    "service/gravitee-management-ui": 1,
    "service/gravitee-portal-ui": 1,
    "service/portainer": 1,
    "service/step-ca": 1,
    "service/crowdsec": 1,
    "service/sonarr": 2,
    "service/radarr": 2,
    "service/lidarr": 2,
    "service/prowlarr": 2,
    "service/seerr": 2,
    "service/sabnzbd": 2,
    "service/bazarr": 2,
    "service/readarr": 2,
    "service/bookshelf": 2,
    "service/huntarr": 2,
    "service/recyclarr": 2,
    "service/kometa": 2,
    "service/servarr-postgres": 2,
    "service/uptime-kuma": 3,
    "service/docker-gc": 3,
    "service/cloudflare-ddns": 3,
    "service/swarm-cronjob": 3,
    "service/traefik-to-unifi": 3,
    "service/unifi-network-mcp": 3,
}

_INCIDENT_LABELS: frozenset[str] = frozenset({"incident", "severity-critical"})

_P0_KEYWORDS: tuple[str, ...] = ("production down", "data loss", "security breach")

_SECURITY_TYPE_LABELS: frozenset[str] = frozenset({"type/security"})

_BUG_TYPE_LABELS: frozenset[str] = frozenset({"type/bug", "type/fix"})

_FEATURE_TYPE_LABELS: frozenset[str] = frozenset({"type/feat", "type/enh"})

_CHORE_TYPE_LABELS: frozenset[str] = frozenset({"type/chore", "type/docs", "type/test", "type/refactor"})

_DOC_COSMETIC_LABELS: frozenset[str] = frozenset({"type/docs"})

# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------


_RANK_TO_LABEL: tuple[str, ...] = ("P0-critical", "P1-high", "P2-medium", "P3-low")

# Lookup table: tier -> bug/fix priority floor rank
_TIER_BUG_FLOOR: dict[int, int] = {0: 1, 1: 2}

# Body keyword signals: word -> priority rank
_BODY_SIGNAL_RANK: dict[str, int] = {
    "broken": 2,
    "blocking": 1,
    "regression": 1,
    "improvement": 2,
    "enhancement": 2,
    "workaround": 2,
}


def _priority_from_rank(rank: int) -> str:
    """Convert a numeric rank (0-3) to a priority label, clamping to bounds."""
    return _RANK_TO_LABEL[max(0, min(3, rank))]


def _is_bug_or_security_type(title: str, label_set: set[str]) -> bool:
    """Check whether the issue is a bug, fix, or security type."""
    if label_set & (_BUG_TYPE_LABELS | _SECURITY_TYPE_LABELS):
        return True
    return conventional_type_from_title(title) in ("bug", "fix", "security")


def _is_security_type(title: str, label_set: set[str]) -> bool:
    """Check whether the issue is specifically a security type."""
    if label_set & _SECURITY_TYPE_LABELS:
        return True
    return conventional_type_from_title(title) == "security"


def _issue_type_rank(title: str, labels: set[str], body_lower: str) -> int | None:
    """Determine starting priority rank from issue type signals.

    Returns None when no type signal is detected.
    """
    title_lower = title.lower()
    if labels & _INCIDENT_LABELS or any(term in title_lower for term in _P0_KEYWORDS):
        return 0

    conv_type = conventional_type_from_title(title)

    if labels & _SECURITY_TYPE_LABELS or conv_type == "security":
        return 1
    if labels & _BUG_TYPE_LABELS or conv_type in ("bug", "fix"):
        return 2
    if labels & _FEATURE_TYPE_LABELS or conv_type in ("feat", "enh"):
        return 2
    if labels & _CHORE_TYPE_LABELS or conv_type in ("chore", "docs", "test", "refactor"):
        return 3

    for keyword, rank in _BODY_SIGNAL_RANK.items():
        if re.search(rf"\b{keyword}\b", body_lower):
            return rank

    return None


def _service_tier(labels: set[str]) -> int | None:
    """Find the highest criticality tier (lowest number) from service labels."""
    tiers = [_SERVICE_TIERS[label] for label in labels if label in _SERVICE_TIERS]
    return min(tiers) if tiers else None


def _blast_radius_bump(labels: set[str]) -> int:
    """Calculate priority bump from label blast radius."""
    affected = sum(1 for label in labels if label.startswith(("service/", "stack/", "system/")))
    cross_stack = sum(1 for label in labels if label.startswith("stack/")) >= 2
    if affected >= 4 or cross_stack:
        return 2
    if affected >= 2:
        return 1
    return 0


def _tier_floor_rank(title: str, label_set: set[str], tier: int) -> int:
    """Compute the priority floor imposed by the service criticality tier.

    Returns 3 (P3-low) when no floor applies, meaning no elevation.
    """
    if _is_security_type(title, label_set) and tier == 0:
        return 0
    if _is_bug_or_security_type(title, label_set):
        return _TIER_BUG_FLOOR.get(tier, 3)
    return 3


def compute_priority(
    *,
    title: str,
    body: str,
    labels: list[str],
) -> str | None:
    """Compute a priority label for an issue using deterministic rules.

    Returns a priority label string (e.g. ``"P2-medium"``) or ``None``
    when no priority can be determined.  Pure function with zero I/O.
    """
    label_set = set(labels)

    # Guard: already has a priority label — skip
    if label_set & _PRIORITY_LABELS:
        return None

    title_lower = title.lower()
    body_lower = f"{title}\n{body}".lower()

    # Hard override: incident labels or P0 keywords in title
    # Per the priority decision framework, P0 keywords ("production down",
    # "data loss", "security breach") are title-only signals.  Body text
    # often contains these phrases in documentation context (severity
    # tables, rollback plans) which must not trigger a false P0.
    if label_set & _INCIDENT_LABELS or any(term in title_lower for term in _P0_KEYWORDS):
        return "P0-critical"

    # Hard override: docs-only issues capped at P3
    is_doc_only = bool(label_set & _DOC_COSMETIC_LABELS) and not (
        label_set & (_BUG_TYPE_LABELS | _SECURITY_TYPE_LABELS | _FEATURE_TYPE_LABELS)
    )
    if is_doc_only:
        return "P3-low"

    # Evaluate the three inputs
    type_rank = _issue_type_rank(title, label_set, body_lower)
    tier = _service_tier(label_set)
    bump = _blast_radius_bump(label_set)

    # Guard: no signals at all — cannot determine priority
    if type_rank is None and tier is None and bump == 0:
        return None

    # Start from the loosest priority and tighten
    base_rank = min(type_rank if type_rank is not None else 3, 3)

    if tier is not None:
        base_rank = min(base_rank, _tier_floor_rank(title, label_set, tier))

    final_rank = max(0, base_rank - bump)
    return _priority_from_rank(final_rank)


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def _resolve_repo(args: argparse.Namespace, runner: GhRunner) -> str:
    """Resolve the target repository from args or auto-detect."""
    if args.repo:
        repo: str = args.repo
        return repo
    return current_repo(runner)


def _build_recommendations(
    issues: list[dict],
) -> list[dict]:
    """Build a list of priority recommendations for issues."""
    recommendations: list[dict] = []
    for issue in issues:
        priority = compute_priority(
            title=issue["title"],
            body=issue.get("body", ""),
            labels=issue.get("labels", []),
        )
        if priority is not None:
            recommendations.append(
                {
                    "number": issue["number"],
                    "title": issue["title"],
                    "current_labels": issue.get("labels", []),
                    "recommended_priority": priority,
                }
            )
    return recommendations


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = ActionableArgumentParser(description="Backfill priority labels on open issues (deterministic).")
    parser.add_argument(
        "--repo",
        default=None,
        help="Repo owner/name (default: auto-detect)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply recommended labels (default: dry-run)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit JSON output",
    )
    return parser


def _output_recommendations(args: argparse.Namespace, recommendations: list[dict]) -> None:
    """Print or log the recommendation table."""
    if args.json_output:
        print(json.dumps(recommendations, indent=2, sort_keys=True))
        return
    logger.info("Priority recommendations (%d issues):\n", len(recommendations))
    for rec in recommendations:
        logger.info(
            "  #%-5d %-12s %s",
            rec["number"],
            rec["recommended_priority"],
            rec["title"],
        )


def _apply_labels(runner: GhRunner, repo: str, recommendations: list[dict]) -> None:
    """Add the recommended priority labels to issues."""
    for rec in recommendations:
        upsert_issue(
            runner=runner,
            repo=repo,
            number=rec["number"],
            title=None,
            body=None,
            labels=[rec["recommended_priority"]],
            assignees=None,
            merge_existing=True,
        )
        logger.info(
            "  Applied %s to #%d",
            rec["recommended_priority"],
            rec["number"],
        )


def _run(args: argparse.Namespace, _parser: argparse.ArgumentParser, runner: GhRunner) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    repo = _resolve_repo(args, runner)

    issues = list_issues(runner=runner, repo=repo, state="open")
    recommendations = _build_recommendations(issues)

    if not recommendations:
        logger.info("No issues need priority labels.")
    else:
        _output_recommendations(args, recommendations)
        if args.apply:
            _apply_labels(runner, repo, recommendations)
        elif not args.json_output:
            logger.info("\nDry-run mode. Use --apply to add labels.")

    return 0


def main(
    *,
    runner_factory: Callable[[], GhRunner] = SubprocessGhRunner,
) -> int:
    """Entry point for ``python -m scripts.ci.backfill_issue_priorities``."""
    return run_actionable_main(
        build_parser=_build_parser,
        handler=_run,
        runner_factory=runner_factory,
        examples=[
            "python -m scripts.ci.backfill_issue_priorities --repo owner/name",
            "python -m scripts.ci.backfill_issue_priorities --repo owner/name --apply",
        ],
        see_also=["docs/repository-standards/priority-decision-framework.md"],
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
