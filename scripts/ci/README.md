# CI automation scripts

Purpose: deterministic CI/CD logic for GitHub Actions workflows. Each script is invoked as a Python module from the repository root.

## Quick Reference (for AI agents)

**Run as modules** from repo root:

```bash
python3 -m scripts.ci.<module>
```

## Scripts

### Issue Priority Triage (event-driven)

- File: `scripts/ci/triage_issue_priority.py`
- Workflow: `.github/workflows/issue-priority-triage.yml`
- Triggers: `issues: [opened, reopened, edited]`

Reads the event payload and calls `compute_priority()` to assign a P0-P3 label. Re-evaluates on each edit. Posts a comment linking to the priority decision framework.

Framework: `docs/repository-standards/priority-decision-framework.md`

### Issue Priority Backfill (batch)

- File: `scripts/ci/backfill_issue_priorities.py`

Dry-run (default):

```bash
python -m scripts.ci.backfill_issue_priorities --repo owner/name
```

Apply labels:

```bash
python -m scripts.ci.backfill_issue_priorities --repo owner/name --apply
```

JSON output:

```bash
python -m scripts.ci.backfill_issue_priorities --repo owner/name --json
```

Scans all open issues and recommends priority labels using the same `compute_priority()` function as the event-driven triage. Safe by default: labels are only applied with `--apply`.

### Keyword Labeler (event-driven)

- File: `scripts/ci/keyword_labeler.py`
- Workflow: `.github/workflows/auto-labeler.yml`

Applies `type/*`, `service/*`, and `stack/*` labels to PRs based on conventional commit prefixes, changed file paths, and Docker image references.

### Sync Directives (push/pull)

- File: `scripts/ci/sync_directives.py`
- Workflows: `sync-directives-push.yml`, `sync-directives-pull.yml`

Copies repository standard files between repos using a hub-and-spoke model. Configuration: `.github/sync-directives.yml`.

### Supporting Modules

| Module | Purpose |
| --- | --- |
| `event_payload.py` | Read GitHub Actions event payload from `GITHUB_EVENT_PATH` |
| `image_service_map.py` | Map Docker image names to `service/*` labels |
| `_decision_utils.py` | Shared decision logic for lint gates, labeling, and triage |
| `write_changed_files.py` | Write `CHANGED_FILES` output for downstream steps |
| `should_run_lint_traefik_swarm.py` | Gate Traefik swarm linting on file changes |

## Lint-Decision Pattern

Each `should_run_lint_*.py` script is a thin CLI wrapper over `_decision_utils.decide()`. The pattern:

1. Define a module-level `_RELEVANT_GLOBS` tuple with fnmatch patterns for the files the linter cares about.
2. In `main()`, call `read_changed_files()` to get the list of changed paths from `changed-files.txt`.
3. Pass the changed paths and globs to `decide()`, which returns a `DecisionResult` (frozen dataclass with `should_run`, `reason`, and `matched_paths`).
4. Print bare `true` or `false` to stdout for CI conditionals.
    Print reason and matched paths to stderr as diagnostics.
    Always return 0 — the script is a gate, not a validator.
5. Catch `OSError` from `read_changed_files()` and fail open (print `true`) so the linter runs when change detection is broken.

To add a new lint gate, create a new `should_run_lint_<name>.py` following this pattern. See `should_run_lint_traefik_swarm.py` as a reference implementation.

## Shared Core: `compute_priority()`

Both triage and backfill scripts import `compute_priority()` from `backfill_issue_priorities`.

This function evaluates issue type, service tier, and blast radius to return a P0-P3 label or `None`.

## Testing

```bash
python -m pytest scripts/ci/tests/ -v
```

All CI scripts maintain 100% test coverage for their core logic.

## Operations

For day-to-day triage workflows (overrides, re-runs, backfills, troubleshooting), see the [Triage Operations Runbook](../../docs/automation/runbooks/triage-operations.md).
