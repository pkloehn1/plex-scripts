# GitHub Actions Workflow Style Guide

## Purpose

Normative rules for GitHub Actions workflows in this repository. Patterns are
aligned across three enforcement tools — the repo's PERM001/PERM002 validator,
Checkov CKV2_GHA_1, and SonarCloud S8264/S8233 — so that a single workflow
style satisfies all three without exceptions or skips.

## Permissions Model (Zero-Trust + Job-Level Grants)

REQUIRE:

- Set `permissions: {}` at the **workflow level** (zero-trust default).
- Declare explicit permissions at the **job level** for each job.
- Grant only the scopes each job actually needs.

NEVER:

- Use `permissions: write-all` or omit `permissions:` entirely (implicit
  write-all).
- Duplicate the same permission at both workflow and job level with non-empty
  values.

### Canonical pattern

```yaml
permissions: {}  # Zero-trust default

jobs:
  build:
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v6
```

### How permissions interact

Job-level `permissions` **completely replaces** (not supplements) workflow-level
permissions for that job. When a job declares its own `permissions` block, all
unmentioned scopes become `none` for that job.

This means `permissions: {}` at workflow level sets the baseline to zero for any
job that does not declare its own block, while jobs with explicit `permissions:`
receive exactly what they declare.

### Tool alignment matrix

<!-- markdownlint-disable MD013 -->

| Tool | Rule | What it checks | `permissions: {}` + job-level |
| ---- | ---- | -------------- | ----------------------------- |
| **PERM001** (repo validator) | Top-level `permissions:` present | Regex match on workflow text | Pass (line present) |
| **PERM002** (repo validator) | Every job declares `permissions:` | Text scan for job-level blocks | Pass (jobs declare) |
| **CKV2_GHA_1** (Checkov) | Top-level not write-all | Attribute check ≠ `write-all` | Pass (`{}` ≠ write-all) |
| **S8264** (SonarCloud) | Read permissions at job level | Job-level declaration present | Pass (job-level grants) |
| **S8233** (SonarCloud) | Write permissions at job level | Job-level declaration present | Pass (job-level grants) |
| **OpenSSF Scorecard** | Token-Permissions | Top-level restrictive + job-level | Full score |

<!-- markdownlint-enable MD013 -->

### Sources

- [GitHub Well-Architected Framework — Securing GitHub Actions Workflows](https://wellarchitected.github.com/library/application-security/recommendations/actions-security/)
  (explicitly recommends `permissions: {}` + job-level)
- [GitHub Docs — Assigning permissions to jobs](https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/assigning-permissions-to-jobs)
- [OpenSSF Scorecard — Token-Permissions check](https://github.com/ossf/scorecard/blob/main/docs/checks.md)
- [Checkov CKV2_GHA_1](https://github.com/bridgecrewio/checkov/blob/main/checkov/github_actions/checks/graph_checks/ReadOnlyTopLevelPermissions.yaml)
- [SonarSource — Securing GitHub Actions with SonarQube](https://www.sonarsource.com/blog/securing-github-actions-with-sonarqube-real-world-examples/)

## Action Pinning

REQUIRE:

- Pin to MAJOR-only tags: `@v6`, `@v7`, `@v3`.
- Use the latest major version available for each action.

NEVER:

- Pin to branches (`@main`, `@master`).
- Pin to exact minor/patch versions (`@v4.1.2`).
- Pin to commit SHAs (`@a1b2c3d`).
- Use unpinned references (`uses: actions/checkout`).

### Rationale

MAJOR-only pins receive security patches automatically without manual SHA
rotation. SHA pinning is common in the open-source ecosystem but creates
maintenance burden and false security (the SHA is only as trustworthy as the
action author's release process). The repo's PIN001/PIN002 validators enforce
this pattern.

## Workflow Placement

REQUIRE:

- Root workflows in `.github/workflows/` (standard triggers).
- Orchestrator workflows in `.github/workflows/orchestrators/` (must contain
  only `uses:`, no `run:` or `shell:`).
- Reusable workflows in `.github/workflows/reusable/` (must define
  `on: workflow_call`).

NEVER:

- Place reusable-only workflows (those with only `workflow_call` trigger) in
  the root `.github/workflows/` directory (PLACE002).

## Concurrency

REQUIRE:

- `concurrency:` block on workflows triggered by `push` or `schedule` to
  prevent parallel runs.
- Use `cancel-in-progress: false` for deployment and sync workflows (ensure
  completion).
- Use `cancel-in-progress: true` for CI/lint workflows on PRs (supersede stale
  runs).

### Pattern

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true  # or false for deployment workflows
```

## Secret Handling

REQUIRE:

- Use secret-availability guards before steps that need secrets:

```yaml
- name: Check for token
  id: token
  env:
    HAS_TOKEN: ${{ secrets.MY_SECRET != '' }}
  run: |
    if [ "$HAS_TOKEN" != "true" ]; then
      echo "::notice::MY_SECRET not configured — skipping."
    fi
```

- Pass secrets via environment variables, never as command-line arguments
  (visible in process listings and logs).
- Use `persist-credentials: false` on `actions/checkout` when the job does not
  need the token after checkout.

NEVER:

- Reference `${{ secrets.* }}` directly in `run:` command strings.
- Hardcode tokens, passwords, or API keys.

## YAML Conventions

REQUIRE:

- Start with `---` document marker.
- End with `...` document marker.
- Comply with yamllint rules (120-char line length, consistent indentation).

## Step Naming

REQUIRE:

- Every `step` must have a descriptive `name:` field.

PREFER:

- Action-oriented names: "Checkout source", "Run tests", "Build image".
- Avoid generic names: "Step 1", "Run script".

## Reusable Workflow Patterns

REQUIRE:

- `on: workflow_call` with explicitly typed `inputs:` and `outputs:`.
- Single responsibility per reusable workflow.

PREFER:

- Delegate complex logic to scripts under `scripts/` rather than embedding
  multi-line `run:` blocks.

## Enforcement

The following tools enforce this style guide:

| Check | Tool | Scope |
| ----- | ---- | ----- |
| PERM001 | `validate_github_actions_architecture.py` | Top-level `permissions:` present |
| PERM002 | `validate_github_actions_architecture.py` | Every job declares `permissions:` |
| PIN001 | `validate_github_actions_architecture.py` | Action ref has `@vN` |
| PIN002 | `validate_github_actions_architecture.py` | Pin is MAJOR-only |
| ORCH001 | `validate_github_actions_architecture.py` | Orchestrators have no `run:`/`shell:` |
| REUSE001 | `validate_github_actions_architecture.py` | Reusable workflows define `workflow_call` |
| PLACE002 | `validate_github_actions_architecture.py` | Root workflows not reusable-only |
| SYNC001 | `validate_github_actions_architecture.py` | No `sync-labels: true` |
| CKV2_GHA_1 | Checkov (Super-Linter) | Top-level permissions not write-all |
| S8264 | SonarCloud | Read permissions at job level |
| S8233 | SonarCloud | Write permissions at job level |

## Sources Reviewed

### Platform Documentation

- [GitHub Docs — Workflow syntax: permissions](https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/assigning-permissions-to-jobs)
- [GitHub Docs — Controlling permissions for GITHUB_TOKEN](https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/controlling-permissions-for-github_token)
- [GitHub Well-Architected — Securing GitHub Actions Workflows](https://wellarchitected.github.com/library/application-security/recommendations/actions-security/)

### Security Frameworks and Scoring

- [OpenSSF Scorecard — Token-Permissions check](https://github.com/ossf/scorecard/blob/main/docs/checks.md)
- [OWASP CI/CD Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/CI_CD_Security_Cheat_Sheet.html)
- [StepSecurity — Determine Minimum GITHUB_TOKEN Permissions](https://www.stepsecurity.io/blog/determine-minimum-github-token-permissions-using-ebpf-with-stepsecurity-harden-runner)

### Static Analysis Tools

- [Checkov CKV2_GHA_1 source](https://github.com/bridgecrewio/checkov/blob/main/checkov/github_actions/checks/graph_checks/ReadOnlyTopLevelPermissions.yaml)
- [SonarSource — Securing GitHub Actions with SonarQube](https://www.sonarsource.com/blog/securing-github-actions-with-sonarqube-real-world-examples/)

### Community Analysis

- [Ken Muse — GitHub Actions Workflow Permissions](https://www.kenmuse.com/blog/github-actions-workflow-permissions/)
- [Christos Galanopoulos — GitHub Actions Permissions](https://christosgalano.github.io/github-actions-permissions/)
