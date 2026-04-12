#!/usr/bin/env python3
"""Triage a single issue's priority from a GitHub Actions event payload.

Reads the ``issues`` event payload, computes a deterministic priority
using :func:`~scripts.ci.backfill_issue_priorities.compute_priority`,
and applies the label via the GitHub API.

Designed to run on ``issues: [opened, reopened, edited, labeled, unlabeled]`` events.
"""

from __future__ import annotations

import json
import logging
import os

from scripts.ci.backfill_issue_priorities import _PRIORITY_LABELS, compute_priority
from scripts.ci.event_payload import read_event_payload
from scripts.github.gh_cli import GhCliError, GhRunner, SubprocessGhRunner, parse_repo

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_label_names(issue: dict) -> list[str]:
    """Extract label name strings from an issue payload.

    Handles both object labels (``{"name": "x"}``) and bare strings.
    """
    raw = issue.get("labels")
    if not isinstance(raw, list):
        return []
    names: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            name = item.get("name")
        elif isinstance(item, str):
            name = item
        else:
            continue
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return sorted(names)


def _remove_label(runner: GhRunner, repo: str, issue_number: int, label: str) -> None:
    """Remove a label from an issue via the GitHub API."""
    owner, name = parse_repo(repo)
    runner.run(
        [
            "gh",
            "api",
            "--method",
            "DELETE",
            f"/repos/{owner}/{name}/issues/{issue_number}/labels/{label}",
        ],
    )


def _add_label(runner: GhRunner, repo: str, issue_number: int, label: str) -> None:
    """Add a label to an issue via the GitHub API."""
    owner, name = parse_repo(repo)
    runner.run(
        [
            "gh",
            "api",
            "--method",
            "POST",
            f"/repos/{owner}/{name}/issues/{issue_number}/labels",
            "--input",
            "-",
        ],
        input_text=json.dumps({"labels": [label]}),
    )


def _post_comment(runner: GhRunner, repo: str, issue_number: int, body: str) -> None:
    """Post a comment on an issue via the GitHub API."""
    owner, name = parse_repo(repo)
    runner.run(
        [
            "gh",
            "api",
            "--method",
            "POST",
            f"/repos/{owner}/{name}/issues/{issue_number}/comments",
            "--input",
            "-",
        ],
        input_text=json.dumps({"body": body}),
    )


def _has_triage_comment(
    runner: GhRunner,
    repo: str,
    issue_number: int,
    priority: str,
) -> bool:
    """Check if the workflow posted a triage comment for *priority*.

    Returns ``True`` when a matching ``Triaged as **<priority>**`` comment
    exists, indicating the label was applied by the workflow rather than a
    human override.
    """
    owner, name = parse_repo(repo)
    output = runner.run(
        [
            "gh",
            "api",
            "--paginate",
            f"/repos/{owner}/{name}/issues/{issue_number}/comments?per_page=100",
        ],
    )
    comments = json.loads(output.stdout)
    if not isinstance(comments, list):
        return False
    marker = f"Triaged as **{priority}**"
    return any(marker in (comment.get("body") or "") for comment in comments)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def triage_issue(
    *,
    runner: GhRunner,
    repo: str,
    issue_number: int,
    title: str,
    body: str,
    labels: list[str],
    server_url: str,
) -> str | None:
    """Compute and apply a priority label for a single issue.

    Returns the applied priority label, or ``None`` if no change was made.
    """
    # Find any existing priority label
    existing_priority = next((lbl for lbl in labels if lbl in _PRIORITY_LABELS), None)

    # Respect human-applied priority labels: if no matching triage comment
    # exists for the current label, a human set it — skip auto-triage.
    # Edge case: if a human removes and re-applies the same label the bot
    # originally set, the old comment still matches and the label is treated
    # as workflow-managed.  This is acceptable — the consequence is the bot
    # re-confirming an identical priority, which is a no-op.
    if existing_priority is not None and not _has_triage_comment(runner, repo, issue_number, existing_priority):
        logger.info(
            "#%d has human-applied %s — skipping auto-triage",
            issue_number,
            existing_priority,
        )
        return None

    # Strip existing priority labels so compute_priority re-evaluates
    filtered_labels = [lbl for lbl in labels if lbl not in _PRIORITY_LABELS]

    priority = compute_priority(title=title, body=body, labels=filtered_labels)
    if priority is None:
        logger.info("No priority determined for #%d", issue_number)
        return None

    # If recomputed priority matches existing, no change needed
    if priority == existing_priority:
        logger.info("#%d already has %s — no change", issue_number, priority)
        return None

    # Remove old priority label if present and different
    if existing_priority is not None:
        logger.info("Removing %s from #%d", existing_priority, issue_number)
        _remove_label(runner, repo, issue_number, existing_priority)

    # Add new priority label
    _add_label(runner, repo, issue_number, priority)
    logger.info("Applied %s to #%d", priority, issue_number)

    # Post explanatory comment
    framework_url = f"{server_url}/{repo}/blob/main/docs/repository-standards/priority-decision-framework.md"
    comment = f"Triaged as **{priority}** ([deterministic priority rules]({framework_url}))."
    _post_comment(runner, repo, issue_number, comment)

    return priority


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    """Entry point for ``python -m scripts.ci.triage_issue_priority``."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    payload = read_event_payload()
    issue = payload.get("issue")
    if not isinstance(issue, dict):
        logger.info("No issue in event payload; exiting.")
        return 0

    # Skip self-triggered events: when the workflow adds/removes a priority
    # label, GitHub fires labeled/unlabeled — ignore to avoid a redundant run.
    action = payload.get("action")
    if action in ("labeled", "unlabeled"):
        event_label = payload.get("label", {})
        if isinstance(event_label, dict) and event_label.get("name") in _PRIORITY_LABELS:
            logger.info("Skipping self-triggered priority label event")
            return 0

    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        logger.error("GITHUB_REPOSITORY not set")
        return 1

    server_url = os.environ.get("GITHUB_SERVER_URL", "https://github.com")

    issue_number = issue.get("number")
    if not isinstance(issue_number, int) or issue_number <= 0:
        logger.error("Invalid or missing issue number in event payload: %r", issue_number)
        return 1

    title: str = issue.get("title", "") or ""
    body: str = issue.get("body", "") or ""
    labels = _extract_label_names(issue)

    runner = SubprocessGhRunner()

    try:
        priority = triage_issue(
            runner=runner,
            repo=repo,
            issue_number=issue_number,
            title=title,
            body=body,
            labels=labels,
            server_url=server_url,
        )
        if priority:
            logger.info("Issue #%d triaged as %s", issue_number, priority)
    except GhCliError as exc:
        logger.error("GitHub CLI error: %s", exc)
        return 1
    except ValueError as exc:
        logger.error("Configuration error: %s", exc)
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
