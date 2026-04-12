---
name: rca
description: Template for documenting Root Cause Analysis (RCA) for production incidents.
---

# Root Cause Analysis Documentation

Use this prompt when documenting root cause analysis for production incidents.

## RCA Documentation Requirements

REQUIRE GitHub Issue for every production incident requiring RCA.

### Issue Template Fields

1. **Problem Statement**: Clear description of the incident
2. **Impact**: Users affected, duration, severity
3. **Timeline**: When detected, when resolved, key events
4. **Framework(s) Used**: OODA, FTA, 5 Whys, Fishbone, etc.
5. **Analysis**: FTA diagram, 5 Whys chains, or OODA timeline
6. **Root Cause**: The underlying cause identified
7. **Contributing Factors**: Secondary causes
8. **Preventive Measures**: Actions to prevent recurrence
9. **Verification**: How preventive measures were validated

### Required Labels

- `incident`
- `rca`
- `severity-critical` | `severity-high` | `severity-medium` | `severity-low`

### Linking Requirements

REQUIRE:

- Incident -> RCA issue link
- RCA issue -> Preventive commits link
- Preventive commits -> RCA issue reference
- Close issue only after preventive measures implemented and verified

### Documentation Principles

ENFORCE DRY:

- RCA content lives in GitHub Issue
- Reference from commits/PRs, do not duplicate
- Operational incidents tracked in Issues, not repository docs

ENFORCE SSOT:

- GitHub Issues are the single source of truth for incident tracking
- Runbook updates reference the originating issue
- Post-incident reviews link to the RCA issue

## RCA Issue Template

```markdown
## Problem Statement

[What happened and when]

## Impact

- **Users affected**: [number/scope]
- **Duration**: [start to resolution]
- **Severity**: [critical/high/medium/low]

## Timeline

| Time  | Event               |
| ----- | ------------------- |
| HH:MM | [Event description] |

## Analysis

### Framework Used: [OODA/FTA/5 Whys/Fishbone]

[Analysis content - diagrams, chains, timelines]

## Root Cause

[The underlying cause]

## Contributing Factors

- [Factor 1]
- [Factor 2]

## Preventive Measures

- [ ] [Action 1] - [Owner] - [Due date]
- [ ] [Action 2] - [Owner] - [Due date]

## Verification

[How we confirmed the fix works]

## References

- Related commits: [links]
- Runbook updates: [links]
- Monitoring changes: [links]
```
