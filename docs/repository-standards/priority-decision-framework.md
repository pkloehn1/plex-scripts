# Priority Decision Framework

How priority labels (P0-P3) are assigned to issues in this repository.

## Purpose

This document defines the triage logic used by the deterministic issue priority triage workflow (`issue-priority-triage.yml`) and serves as the human-readable reference for the maintainer.
Adapted from the ITIL Impact x Urgency model, simplified for a single-maintainer homelab.

## Priority Definitions

| Priority | When to use | Response |
| --- | --- | --- |
| P0-critical | Service outage, data loss, active security exposure | Drop everything |
| P1-high | Broken functionality, security hardening, Tier 0 service bug | Next work session |
| P2-medium | Non-critical bug, moderate improvement, most feature work | This week |
| P3-low | Cosmetic, documentation, nice-to-have | Backlog |

## Three Inputs

The agent evaluates three inputs from each issue and selects the highest resulting priority.

### Input 1 --- Issue Type

Derived from the title prefix, existing labels, and body keywords.

| Signal | Starting priority |
| --- | --- |
| Outage, incident, or active security breach | P0 |
| Bug or fix | P1-P2 (depends on service tier) |
| Feature or enhancement | P2-P3 |
| Chore, docs, cosmetic | P3 |

Detection sources:

- Title prefix: conventional commit type (`bug:`, `fix:`, `security:`, `feat:`, `chore:`, `docs:`)
- Labels: `incident`, `type/bug`, `type/fix`, `type/security`, `type/feat`, `type/chore`, `type/docs`
- Body keywords: "broken", "blocking", "regression", "improvement", "enhancement", "workaround" (P0 keywords are title-only; see Hard Overrides)

### Input 2 --- Service Criticality Tier

Derived from `service/*` labels, title scope (e.g., `fix(servarr):`), and body content.
The tier sets a priority floor for bugs and security issues.

| Tier | Services | Bug/fix floor | Security floor |
| --- | --- | --- | --- |
| Tier 0 --- Infra | traefik, socket-proxy, authentik, authentik-postgres | P1 | P0 |
| Tier 1 --- Core | gravitee-*, portainer, step-ca, crowdsec | P2 | P1 |
| Tier 2 --- Apps | sonarr, radarr, lidarr, prowlarr, seerr, sabnzbd, bazarr, readarr, bookshelf, huntarr, recyclarr, kometa, servarr-postgres | Standard | Standard |
| Tier 3 --- Ops | uptime-kuma, docker-gc, cloudflare-ddns, swarm-cronjob, traefik-to-unifi, unifi-network-mcp | Standard | Standard |

Rationale: Tier 0 services are single points of failure.
Traefik handles all ingress, socket-proxy gates Docker API access, and Authentik gates all SSO-protected UIs.

A bug in these services causes cascading outage.
Tier 1 services are core platform but degrade more gracefully.

### Input 3 --- Blast Radius

Derived from the count of `service/*`, `stack/*`, and `system/*` labels on the issue, plus body content listing multiple affected services or paths.

| Blast radius | Priority effect |
| --- | --- |
| Single service, single server | No change |
| 2-3 services or 2+ stacks | Bump one level (P3 to P2, P2 to P1) |
| 4+ services or cross-stack | Bump two levels, cap at P0 |

## Hard Overrides

These bypass the three-input evaluation:

- `incident` or `severity-critical` label present: forced P0
- Title contains "production down", "data loss", or "security breach": forced P0
- Issue is purely cosmetic or documentation-only: capped at P3

## Conflict Resolution

The highest signal wins. Service tier sets a priority floor.

Blast radius can elevate above that floor. No signal can lower the priority below the floor set by a higher-ranked signal.

## Human Override

If an issue has a priority label but no matching `Triaged as **<priority>**` comment, the workflow treats it as human-applied and skips auto-triage entirely.

To override: delete the triage comment, remove the current priority label, and apply the desired label. See the [Triage Operations Runbook](../automation/runbooks/triage-operations.md).

## Implementation

The priority logic is implemented as a pure function `compute_priority()` in `scripts/ci/backfill_issue_priorities.py`.
Two entry points share this function:

- **Event-driven** (`scripts/ci/triage_issue_priority.py`): runs on issue open, reopen, or edit. Strips any existing priority label, re-computes, and applies via the GitHub API.
- **Batch** (`scripts/ci/backfill_issue_priorities.py`): scans all open issues. Dry-run by default; `--apply` to add labels.

Both produce identical, deterministic results with zero AI cost.

## Reusability

Other repositories can adopt this framework by:

1. Copying this document
2. Updating the service tier table for their own services
3. Deploying the `issue-priority-triage.yml` workflow and the `scripts/ci/` triage scripts (propagated via `sync-directives.yml`)

## See Also

- [`.github/labels-hub.yml`](../../.github/labels-hub.yml) --- P0-P3 label definitions (SSOT)
- [`.github/workflows/issue-priority-triage.yml`](../../.github/workflows/issue-priority-triage.yml) --- the deterministic workflow that applies these rules
- [`scripts/ci/README.md`](../../scripts/ci/README.md) --- CI scripts reference
- [Triage Operations Runbook](../automation/runbooks/triage-operations.md) --- day-to-day triage procedures
