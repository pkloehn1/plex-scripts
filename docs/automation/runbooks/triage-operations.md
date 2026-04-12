# Triage Operations Runbook

Table of contents:

- [1. Purpose](#1-purpose)
- [2. Scope](#2-scope)
- [3. Prerequisites](#3-prerequisites)
- [4. How priority triage works](#4-how-priority-triage-works)
- [5. Override a computed priority label](#5-override-a-computed-priority-label)
  - [5.1 Re-enable workflow management after an override](#51-re-enable-workflow-management-after-an-override)
- [6. Re-run triage after manual label changes](#6-re-run-triage-after-manual-label-changes)
- [7. Run backfill dry-run and interpret output](#7-run-backfill-dry-run-and-interpret-output)
- [8. Add a new service to the tier table](#8-add-a-new-service-to-the-tier-table)
- [9. Troubleshooting](#9-troubleshooting)
- [10. References](#10-references)

## 1. Purpose

Operational procedures for day-to-day issue priority triage: overriding computed labels, re-running triage, running batch backfills, extending the service tier table, and troubleshooting.

For the priority logic itself (P0-P3 definitions, three-input model, tier floors, blast radius), see the [Priority Decision Framework](../../repository-standards/priority-decision-framework.md).

## 2. Scope

- The event-driven workflow: `.github/workflows/issue-priority-triage.yml`
- The batch backfill script: `scripts/ci/backfill_issue_priorities.py`
- The shared core function: `compute_priority()` in `backfill_issue_priorities.py`
- The event handler: `scripts/ci/triage_issue_priority.py`

## 3. Prerequisites

- Repository cloned locally with the Python venv bootstrapped (`.venv/`)
- `gh` CLI authenticated for the target repo
- Write access to issue labels on the target repo

## 4. How priority triage works

The workflow fires on `issues: [opened, reopened, edited, labeled, unlabeled]`. Each event triggers `triage_issue_priority.py`, which:

1. Reads the GitHub event payload.
2. Extracts the issue title, body, and labels.
3. Strips existing priority labels and calls `compute_priority()`.
4. If the computed priority differs from the current label, removes the old label and applies the new one.
5. Posts a triage comment linking to the priority framework, e.g.: `Triaged as **P2-medium** ([deterministic priority rules](<url>)).`

### 4.1 Self-loop guard

When the workflow adds or removes a priority label, GitHub fires a `labeled`/`unlabeled` event. The script detects the triggering label is a priority label and skips re-evaluation to prevent loops.

### 4.2 Human override detection

If an issue has a priority label but no matching triage comment, the script treats the label as human-applied and skips auto-triage. The triage comment format is `Triaged as **<priority>**`.

## 5. Override a computed priority label

To permanently override the workflow-assigned priority:

1. Navigate to the issue on GitHub.
2. Find the workflow comment that says `Triaged as **<current-priority>**`.
3. Delete that comment (three-dot menu on the comment, then "Delete").
4. Remove the current priority label from the issue.
5. Apply the desired priority label manually.

The workflow will not re-triage because there is no matching triage comment for the new label (section 4.2).

### 5.1 Re-enable workflow management after an override

If you later want the workflow to manage the issue again:

1. Remove the human-applied priority label from the issue.
2. Verify there is no remaining `Triaged as **<priority>**` comment for the removed label. If one exists from a previous workflow run, delete it.
3. Trigger a new event: edit the issue title or body, or add/remove a non-priority label.
4. The workflow fires, posts a new triage comment, and resumes management.

The key requirement is that no priority label exists without a matching triage comment. As long as the issue is in that state, the workflow treats it as needing fresh triage.

## 6. Re-run triage after manual label changes

Adding or removing `service/*`, `stack/*`, or `type/*` labels fires `labeled`/`unlabeled` events that automatically trigger the workflow. No manual edit is needed.

1. Add or remove the desired `service/*`, `stack/*`, or `type/*` labels.
2. The workflow fires, strips existing priority labels, re-runs `compute_priority()` with the updated label set, and applies the new result.

**Exception — human overrides:** if a human-applied priority label is present (section 4.2), label changes skip auto-triage. See [section 5.1](#51-re-enable-workflow-management-after-an-override).

## 7. Run backfill dry-run and interpret output

The backfill script scans all open issues and recommends priority labels using the same `compute_priority()` function as the event-driven workflow.

### 7.1 Dry-run (default)

```bash
.venv/bin/python -m scripts.ci.backfill_issue_priorities --repo <owner/repo>
```

Output: a formatted table with columns for issue number, title, current labels, and recommended priority. Issues that already have a priority label are skipped (`compute_priority()` returns `None`).

### 7.2 JSON output

```bash
.venv/bin/python -m scripts.ci.backfill_issue_priorities --repo <owner/repo> --json
```

Returns a structured JSON array for scripting or piping to `jq`.

### 7.3 Apply labels

```bash
.venv/bin/python -m scripts.ci.backfill_issue_priorities --repo <owner/repo> --apply
```

Applies the recommended priority labels to all open issues that do not already have one. Run the dry-run first to review recommendations.

### 7.4 Interpreting results

- `None` in the recommended column means the issue already has a priority label and was skipped.
- If a recommendation seems wrong, check the issue's `type/*`, `service/*`, and `stack/*` labels — these are the inputs to `compute_priority()`.
- Body keywords (`broken`, `blocking`, `regression`, `improvement`, `enhancement`, `workaround`) also influence the type rank. Check the issue body if the priority seems unexpectedly high.

## 8. Add a new service to the tier table

When a new service is added to the project:

1. Open `scripts/ci/backfill_issue_priorities.py`.
2. Find the `_SERVICE_TIERS` dictionary.
3. Add an entry mapping `service/<name>` to the appropriate tier:

  - `0` = Tier 0 (Infrastructure): bug floor P1, security floor P0
  - `1` = Tier 1 (Core): bug floor P2, security floor P1
  - `2` = Tier 2 (Apps): standard rules
  - `3` = Tier 3 (Ops): standard rules

4. Update the tier table in `docs/repository-standards/priority-decision-framework.md`.
5. Run the backfill dry-run (section 7.1) to verify the new service's priority recommendations are correct.
6. Run the test suite to confirm no regressions:

```bash
.venv/bin/python -m pytest scripts/ci/tests/ -v
```

## 9. Troubleshooting

### 9.1 Workflow not firing

- Verify the issue event type is in the trigger list: `opened`, `reopened`, `edited`, `labeled`, `unlabeled`.
- Check the Actions tab for the `issue-priority-triage` workflow. If no run appears, the event may not have matched the trigger conditions.
- Confirm the workflow file exists at `.github/workflows/issue-priority-triage.yml` on the default branch.

### 9.2 Label not applied

- Check the workflow run logs for "human-applied" skip messages. If the issue has a priority label without a matching triage comment, the workflow respects the human override.
- Verify the issue has `type/*`, `service/*`, or `stack/*` labels. Without these inputs, `compute_priority()` may not produce a result.
- Check for the self-loop guard: if the triggering event was a priority label change, the workflow skips to prevent infinite loops.

### 9.3 Priority seems wrong

- Run the backfill dry-run (section 7.1) and compare the recommendation against the current label.
- Check all three inputs: issue type (title prefix, labels, body keywords), service tier (`_SERVICE_TIERS`), and blast radius (count of `service/*` and `stack/*` labels).
- Hard overrides take precedence: `incident` or `severity-critical` labels force P0. Pure `type/docs` issues are capped at P3.

### 9.4 Backfill reports stale data

- The backfill script fetches issues via the GitHub API at runtime. If results seem stale, verify your `gh` CLI is authenticated and has access to the target repo.
- Rate limiting: if scanning many issues, the script may hit the GitHub API rate limit. Wait and retry, or use a personal access token with higher limits.

## 10. References

- [Priority Decision Framework](../../repository-standards/priority-decision-framework.md) — priority logic (SSOT)
- [Issue Priority Triage Workflow](../../../.github/workflows/issue-priority-triage.yml) — GitHub Actions workflow
