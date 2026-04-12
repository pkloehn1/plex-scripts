---
name: start-work
description: Bootstrap issue-driven sessions with pre-flight, issue selection, branch creation, and implementation planning
---

# Start Work — Issue-Driven Session Bootstrap

Automate DevSecOps workflow steps 0-6 into a single invocation for single-issue and multi-issue sessions.

- Full workflow: `docs/repository-standards/devsecops-workflow.md`
- Multi-issue sessions: `docs/repository-standards/ai-batch-session-sop.md`

## Phase 0 — Pre-flight

Verify the development environment is ready:

1. Check `.venv/` exists:

```bash
ls .venv/Scripts/python 2>/dev/null || ls .venv/bin/python 2>/dev/null
```

2. Verify git signing is configured:

```bash
.venv/bin/python -m scripts.devops.setup_git_signing --check-only
```

3. Confirm clean working tree on `main`:

```bash
git status --porcelain
git branch --show-current
```

If any check fails, report the issue and stop.

## Phase 1 — Issue discovery

If the user provided an issue number (e.g., `/start-work 45`), skip phases 1 and 2 and proceed directly to phase 3.

Otherwise, fetch all open issues:

```bash
.venv/bin/python -m scripts.github.list_issues --repo <owner/name> --state open
```

Present a table to the user:

```text
| # | Title | Priority | Estimate | Assignee |
|---|-------|----------|----------|----------|
```

Ask the user: **single-issue or multi-issue session?**

## Phase 2 — Recommendation and selection

### Single-issue mode

Recommend the top 3 issues ranked by:

1. Priority label (P0 > P1 > P2 > P3)
2. AC clarity (unambiguous, testable criteria rank higher)
3. Estimated complexity (lower complexity preferred)

Present recommendations and wait for user selection.

### Multi-issue mode

Apply the batch SOP scoring matrix from `docs/repository-standards/ai-batch-session-sop.md`:

| Factor                             | Weight | 1 (low)                 | 3 (high)                        |
| ---------------------------------- | ------ | ----------------------- | ------------------------------- |
| File overlap with other candidates | 2x     | No shared files         | Same file modified              |
| Estimated complexity               | 1x     | Single file, mechanical | Multi-file, judgment calls      |
| Dependency on other issues         | 2x     | Independent             | Must merge before/after another |
| AC clarity                         | 1x     | Unambiguous, testable   | Vague, needs interpretation     |

Score each candidate (range: 6-18). Present scores and recommend a batch group. Classify issue pairs as independent, overlapping, or dependent.

Wait for user to confirm the selected issues.

Skipped when an issue number was provided directly.

## Phase 3 — Issue deep-dive

Fetch the full issue details:

```bash
.venv/bin/python -m scripts.github.issue_fetch --repo <owner/name> --number <N> --json
```

For each selected issue:

1. Restate the acceptance criteria and scope.
2. **Research gate**: look up provider documentation for third-party tools or external services (bounded, not open-ended).
3. **Confidence gate**: if confidence on any AC item is below 95%, ask clarifying questions before proceeding.

Wait for user to confirm scope.

## Phase 4 — Branch creation

Create a branch for each issue (never construct branch names manually):

```bash
.venv/bin/python -m scripts.devops.start_issue_work --repo <owner/name> --issue <N>
```

For multi-issue sessions:

- Create branches in dependency order.
- Present the merge order to the user per batch SOP.
- Use `--allow-non-main` for dependent branches.

## Phase 5 — Implementation plan

Read all files to modify plus applicable style guides and path-scoped instructions for each file type:

| File type   | Style guide                                                         | Instructions                                  |
| ----------- | ------------------------------------------------------------------- | --------------------------------------------- |
| Python      | `docs/repository-standards/style-guides/python-style-guide.md`      | `.github/instructions/python.instructions.md` |
| Docker/YAML | `docs/repository-standards/style-guides/docker-yaml-style-guide.md` | `.github/instructions/docker.instructions.md` |
| Markdown    | `docs/repository-standards/style-guides/markdown-style-guide.md`    | (none)                                        |
| Shell       | `docs/repository-standards/style-guides/shell-style-guide.md`       | (none)                                        |
| CI/CD       | (none)                                                              | `.github/instructions/cicd.instructions.md`   |

Generate the plan using the batch SOP template format:

```text
## Issue N: #<number> --- <title>

### Files

<paths to create or modify>

### Convention anchors

<style guide paths to re-read after compression>

### Research findings

<current state of target files, constraints>

### Merge-order

<position in sequence, dependencies>

### Fix approach

<1-3 sentences>

### Commit strategy

<number of commits, grouping rationale>

### AC verification

- [ ] <AC item 1> --- <how to verify>
- [ ] <AC item 2> --- <how to verify>

### Validation

<specific commands or checks>
```

Wait for user to approve the plan before implementing.

## Phase 6 — PR bootstrap

After implementation is complete:

1. Remind the user to push the branch.
2. After the user confirms the push, sync the PR:

```bash
.venv/bin/python -m scripts.github.pr_upsert \
  --repo <owner/name> --title "<conventional commit title>" \
  --base main --head <branch> --auto-summary --issue <N>
```

For multi-issue PRs, include all issue numbers:

```bash
.venv/bin/python -m scripts.github.pr_upsert \
  --repo <owner/name> --title "<title>" \
  --base main --head <branch> --auto-summary --issue <N1> --issue <N2>
```

## Safety rules

- NEVER run `git push` — user owns all remote sync.
- NEVER use raw `gh` commands — use repo helper scripts.
- NEVER construct branch names manually — use `start_issue_work`.
- MUST wait for user confirmation at phase 3 (scope) and phase 5 (plan) before proceeding.
- MUST use `issue_fetch` for single-issue data retrieval.
- MUST follow one-file-per-commit rule (Python exception: impl + test together).
