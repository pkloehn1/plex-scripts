# AI Batch Session SOP

## Purpose

Standard operating procedure for sessions where a single human operator and AI agent work through multiple issues in one sitting.
Extends the [DevSecOps workflow](devsecops-workflow.md) with batch-specific scoring, planning, execution, and review patterns.

Scope: homelab-scale, single operator + AI agent. Not enterprise process.

## When to Use

- Working 3+ issues in a single session.
- Issues share files, dependencies, or merge-order constraints.
- Session will span context compression boundaries.

For single-issue work, follow the [DevSecOps workflow](devsecops-workflow.md) directly.

## Phase 1 --- Issue Scoring and Batch Selection

### Scoring Matrix

Score every candidate issue before selecting the batch. Lower total = better batch candidate.

| Factor | Weight | 1 (low) | 3 (high) |
| --- | --- | --- | --- |
| File overlap with other candidates | 2x | No shared files | Same file modified |
| Estimated complexity | 1x | Single file, mechanical | Multi-file, judgment calls |
| Dependency on other issues | 2x | Independent | Must merge before/after another |
| AC clarity | 1x | Unambiguous, testable | Vague, needs interpretation |

Minimum score: 6. Maximum score: 18.

### Batch Selection Rules

REQUIRE:

- Read the full issue body (title + body + AC) before scoring. Do not skip the issue body.
- Group issues that modify overlapping files into sequential merge order.
- Present scores to the operator for approval before starting work.

NEVER:

- Select an issue without scoring it first.

### Merge-Order Dependencies

Classify each issue pair:

- **Independent**: no shared files, any execution order works.
- **Overlapping**: shared files but no logical dependency. Sequence so later PRs rebase cleanly.
- **Dependent**: one must merge before the other can start. Merge prerequisite first.

Merge each PR before starting the next issue. This eliminates rebase cascades caused by batch-then-merge.

## Phase 2 --- Per-Issue Work Plan

Each issue in the batch plan requires codebase research followed by the plan template below.

### Codebase Research (before planning)

REQUIRE:

- Read every file the issue will modify. For new files, review adjacent files in the target directory and the relevant style guide.
- Grep for references to functions, labels, or config values the issue touches.
- Verify current state matches assumptions (e.g., confirm a linter config value before documenting it).
- Record findings in the plan template's **Research findings** field.

### Plan Template

```markdown
## Issue N: #<number> --- <title>

**Files:** <paths to create or modify>

**Convention anchors:** <style guide paths to re-read after compression>

**Research findings:** <current state of target files, discovered references, constraints>

**Merge-order:** <position in sequence, dependencies on other issues>

**Fix approach:** <1-3 sentences>

**Commit strategy:** <number of commits, grouping rationale>

**AC verification:**

- [ ] <AC item 1> --- <how to verify>
- [ ] <AC item 2> --- <how to verify>

**Validation:** <specific commands or checks>
```

### Convention Anchors by File Type

Re-read these files before implementing changes to the corresponding file type. Conventions do not survive context compression.

| File type | Anchor paths |
| --- | --- |
| Markdown | `docs/repository-standards/style-guides/markdown-style-guide.md` |
| Python | `.github/instructions/python.instructions.md`, `docs/repository-standards/style-guides/python-style-guide.md` |
| Docker Compose | `.github/instructions/docker.instructions.md`, `docs/repository-standards/style-guides/docker-yaml-style-guide.md` |
| CI/CD workflows | `.github/instructions/cicd.instructions.md` |
| All issues | `.github/copilot-instructions.md` (Git Safety, Operating Principles sections) |

## Phase 3 --- Execution Checklist

### Pre-Flight (once per session)

- [ ] Verify repo venv is bootstrapped and Git signing is configured.
- [ ] Fetch and review all candidate issues.
- [ ] Score issues using the Phase 1 matrix.
- [ ] Draft batch plan with per-issue sections (Phase 2 template).
- [ ] Confirm batch plan with operator.

### In-Flight (repeat per issue)

- [ ] Re-read convention anchor files for this issue's file types.
- [ ] Cross-reference each AC item against relevant style guides before implementing.
- [ ] If modifying third-party config, research upstream documentation first.
- [ ] Create branch via `scripts.devops.start_issue_work`.
- [ ] Implement changes following the plan.
- [ ] Commit per the one-file-per-commit rule (Python impl+test exception applies).
- [ ] After operator pushes, create PR via `scripts.github.pr_upsert --auto-summary --issue N`.
- [ ] **REQUIRE: After each push, sweep ALL open PRs for review comments (Phase 4). Do not start the next issue until every thread is resolved.**
- [ ] Hand off to [DSO workflow steps 9-11](devsecops-workflow.md) (Review → Merge → Cleanup). Operator merges the PR; agent deletes the local branch.
- [ ] Run `git stash list` to confirm no forgotten stashes.

### Post-Flight (once per session)

- [ ] Verify all session PRs are merged with green CI.
- [ ] Run `git stash list` to confirm empty.
- [ ] Confirm all session branches are deleted: `git branch` shows no branches created for this session's issues.
- [ ] Conduct Start/Stop/Continue retrospective (see Retrospective Integration below).

## Phase 4 --- PR Review Comment Integration

### Proactive Review Sweep

After each push (not just at session end):

REQUIRE:

- Check ALL open PRs for new review comments, not just the current PR.
- Use `triage_review_comments` to list and resolve comments in bulk.
- Parse the review body for suppressed comments in `<details>` blocks (see below).
- Follow the [DSO review workflow](devsecops-workflow.md) for each comment: analyze, recommend, user-selects, implement.
- Use the [DSO presentation format](devsecops-workflow.md#2-present-recommendations) for options tables.
- Verify every thread is resolved before starting the next issue.

NEVER:

- Group review findings by theme in initial presentation. Present each comment individually.
- Move to the next issue before confirming all threads are resolved.
- Implement fixes before the operator selects an option.

### Checking for Suppressed Comments

Copilot code review wraps lower-confidence findings in HTML `<details>` blocks within the review body.
These do not appear as top-level comments. Check the review body for collapsed sections after each review.

## Retrospective Integration

At session end, capture findings in Start/Stop/Continue format:

- **START**: new practices to adopt.
- **STOP**: practices causing friction or errors.
- **CONTINUE**: practices working well.

When a finding repeats across 2+ sessions, open a docs issue to update this SOP.

## See Also

- [DevSecOps Workflow](devsecops-workflow.md) --- single-issue workflow (SSOT)
- [Priority Decision Framework](priority-decision-framework.md) --- issue priority triage
- [Documentation Standards](documentation-standards.md) --- docs change rules
- [GitHub Platform Standards](github-platform-standards.md) --- PR review thread handling
