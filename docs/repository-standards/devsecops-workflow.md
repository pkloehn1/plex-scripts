# DevSecOps Workflow (Homelab)

## Purpose

Define a single, one-way-to-win workflow for doing work in this repository.

Scope:

- issue-driven changes
- local branch workflows
- pull requests and review
- merge and cleanup

This document is the single source of truth (SSOT) for workflow behavior. It is designed for a homelab environment where changes may impact live services.

## Non-negotiables

- Keep changes small and incremental.
- Never commit secrets.
- Prefer configuration over hardcoded environment-specific values.
- Commit `.pre-commit-config.yaml` separately (its own commit) before committing other files so hooks are updated before subsequent commits run.
  Still observe the one-file-per-commit rule.
  **Python exception**: implementation files and their corresponding test files MUST be committed together to maintain 100% test coverage.
- **Never bypass control tools without human approval.**
  Do not use `--no-verify`, `SKIP=<hook>`, inline suppressions (`# noqa`, `# nosec`, `# type: ignore`), or any mechanism that disables a linter, security scanner, or pre-commit hook.
  When a control tool fails repeatedly (>2 attempts), escalate to the user with error details instead of bypassing.
- Treat merges as squash merges.
- **All commits must be signed** (enforced by pre-commit hooks; CI skips signing checks).
- **Commit hygiene**: if a commit fails (pre-commit hook failure), immediately unstage the file (`git reset HEAD <file>`) before attempting fixes.
  Never leave files staged after a failed commit — it prevents accidental bundling of unrelated changes.

## Roles

- **Agent**: makes local changes, runs validations, creates commits, can create PRs after the user publishes a branch.
- **User**: owns git push and final merge operations.

## Workflow task list

| Step | Phase            | Trigger                     | Agent responsibilities                                                                                                                                                                                                                           | User responsibilities                                                          | Evidence / artifacts                     | Gate (pass/fail)                                               |
| ---: | ---------------- | --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------ | ---------------------------------------- | -------------------------------------------------------------- |
|    0 | Setup            | First-time setup            | Verify repo venv is bootstrapped and Git signing is configured (pre-commit hook will check).                                                                                                                                                     | Run the bootstrap and Git signing setup commands (see "Setup commands" below). | Venv ready; Git signing config verified. | Signing is configured.                                         |
|    1 | Intake           | User requests work on issue | Fetch issue details via repo GitHub helpers. Restate acceptance criteria and scope.                                                                                                                                                              | Confirm scope, target role (edge/internal), and operational constraints.       | Issue JSON summary, short checklist.     | Scope is unambiguous.                                          |
|    2 | Branch           | Issue accepted              | Create branch using `scripts.devops.start_issue_work`. Do not manually construct branch names. Do not push.                                                                                                                                      | None.                                                                          | Local branch name and base.              | Branch exists, clean working tree.                             |
|    3 | PR bootstrap     | User has pushed             | Create PR (ready-for-review) via `scripts.github.pr_upsert` as soon as the user has pushed the branch. Do not defer to end of implementation — early PRs trigger CI checks (SonarQube, Super-Linter) that the IDE cannot reliably catch locally. | Push branch to remote.                                                         | PR URL.                                  | PR targets correct base/head; required contexts start running. |
|    4 | Plan             | Before edits                | Write a short plan with files + validation steps. Keep it testable.                                                                                                                                                                              | Confirm plan if scope is medium/high.                                          | Plan bullets.                            | Plan matches acceptance criteria.                              |
|    5 | Implement        | Plan approved               | Make smallest changes that satisfy the issue. Follow repo style guides.                                                                                                                                                                          | Provide environment values via env files/secrets at deploy time.               | Focused diffs.                           | No secrets; minimal scope.                                     |
|    6 | Tests            | Any non-trivial logic       | Add/extend unit tests for non-trivial logic.                                                                                                                                                                                                     | None.                                                                          | Test output.                             | Tests pass.                                                    |
|    7 | Local validation | Before commit               | Run repo hooks once via git commit (avoid double-running).                                                                                                                                                                                       | Ensure sudo token is primed if Docker-based hooks require it.                  | Pre-commit output.                       | All hooks pass.                                                |
|    8 | Security         | New/changed code            | Run required security checks for the touched tech (see references). Fix findings and re-run.                                                                                                                                                     | Authenticate tools if prompted (when needed).                                  | Scan outputs + remediation notes.        | No new high severity issues (or explicitly accepted).          |
|    9 | Review           | Feedback received           | Make focused fixes, keep diffs minimal, rerun validations as needed.                                                                                                                                                                             | Approve when ready.                                                            | Updated commits.                         | Required contexts are green.                                   |
|   10 | Merge            | PR approved                 | Do not merge unless asked. Provide diff-based verification guidance under squash merges. CalVer tag `v{YYYY.0M.MICRO}` and GitHub Release are automatically created on push to main.                                                             | Perform squash merge.                                                          | Merge completed.                         | Main contains the change.                                      |
|   11 | Cleanup          | After merge                 | Verify branch content is in main via diff. Delete local branch and prune remotes.                                                                                                                                                                | None.                                                                          | Clean local branches.                    | No stale work branches.                                        |

## Definition of done (homelab)

Use this checklist when relevant to the change type.

- Documentation
  - Any new operational procedure belongs in a single runbook location.
  - No duplicated procedures across docs.
- Docker Swarm / infrastructure
  - No image tags set to latest.
  - Secrets are handled via Docker secrets when applicable.
  - Persistent storage is explicit for stateful services.
  - Log rotation is configured.
- Security
  - Do not hardcode environment-sensitive values when a config or env var is the intended mechanism.
  - Run required scans for new or changed first-party code.
- Version tagging
  - CalVer tag and GitHub Release created on main after merge (automated by CI).

## Setup commands

- Bootstrap repo venv:
  - Windows: `py -3 -m scripts.dev.bootstrap_venv`
  - Linux/macOS: `python3 -m scripts.dev.bootstrap_venv`
- Setup Git commit signing:
  - If venv is available: `.venv/bin/python -m scripts.devops.setup_git_signing`
  - If venv is unavailable: `python3 -m scripts.devops.setup_git_signing`
- Ruff formatting (match Super-Linter config):
  - `.venv/bin/ruff format --config .github/linters/.ruff.toml <paths>`

## PR review comment handling

When the agent receives PR review comments (from Copilot, reviewers, or automated tools), follow this sequence:

### 1. Analyze

Read each comment. Identify root cause, scope, and validity. Do not start coding before completing analysis.

### 2. Present recommendations

For each comment, present 2-3 options using the format below:

- State which option the agent recommends.
- Rate each option's **Resilience** — how long the solution holds before needing revisiting:
  - **Short-term**: quick fix, likely to break again or need revisiting soon.
  - **Medium-term**: decent solution with known flaws, holds for a while.
  - **Long-term**: resilient, handles future complexity.
- Describe the trade-off (effort, maintenance burden, coverage) for each.

Format (using Markdown):

```markdown
## Comment N — <one-line summary>

| Finding #    | Rec #           | Approach        | Resilience      | Description   |
| ------------ | --------------- | --------------- | --------------- | ------------- |
| 1 <file>     | A (recommended) | <approach name> | **Short-term**  | <description> |
| <Short Desc> | B               | <approach name> | **Medium-term** | <description> |
|              | C               | <approach name> | **Long-term**   | <description> |
| 2 <file>     | A (recommended) | <approach name> | **Short-term**  | <description> |
| <Short Desc> | B               | <approach name> | **Medium-term** | <description> |
|              | C               | <approach name> | **Long-term**   | <description> |
```

### 3. User selects

Wait for user approval before implementing. Do not fix code before the user selects an option.

### 4. Implement and resolve

After the user selects options:

1. Implement the selected fix and commit (following one-file-per-commit rules).
2. Reply to each review comment with the fix commit SHA and a brief description.
3. Resolve the review thread.

Use the `triage_review_comments` flow script to reply and resolve in bulk:

```bash
.venv/bin/python -m scripts.github.triage_review_comments \
  --repo <owner/name> --pr <NUMBER> --author-substring <author> \
  --replies-json '[{"comment_id": <ID>, "body": "Fixed in <SHA>. <description>"}]'
```

## PR checklist handling (SSOT)

- When drafting PR bodies, mark checklist items as complete only when verified.
- If a checklist item does not apply to the change, leave the checkbox unchecked and append "(N/A)" to the item text.
- Do not guess on items that require local validation unless the validation was run.

## PR body standards for multi-issue PRs

When a PR closes two or more issues, use the structured format below instead of flat lists. See PR #192 for a real-world example.

### Summary

Use per-issue bold headings with 1-2 sentence outcome descriptions:

```markdown
**Issue #NNN — Short title:**
One-two sentence outcome description.

**Issue #NNN — Short title:**
One-two sentence outcome description.
```

Single-issue PRs retain the existing bullet-point summary format.

### When to group issues in a single PR

- Group issues when they share implementation dependencies (e.g., a migration that triggers linting fixes).
- Keep issues in separate PRs when they are independently testable and have no shared code changes.
- Default: 1 issue = 1 PR. Only combine when the issues are genuinely coupled.

## References (source of truth)

- Dependabot image update verification: docs/automation/runbooks/dependabot-image-update-verification-sop.md
- Documentation standards: docs/repository-standards/documentation-standards.md
- Git branching: docs/repository-standards/git-branching.md
- Docker Compose style: docs/repository-standards/style-guides/docker-yaml-style-guide.md
- Issue template (work-package + incident-rca): .github/ISSUE_TEMPLATE/work-package.yml
- Pull request template: .github/pull_request_template.md
- Data management (config, secrets, persistence): .github/instructions/data_management.instructions.md
- GitHub automation constraints (helpers, no git push): .github/copilot-instructions.md
- GitHub platform standards (reviews, required contexts): docs/repository-standards/github-platform-standards.md
- Checks parity matrix (local vs CI): docs/ci/checks-parity-matrix.md
- CI runs pre-commit hooks in `.github/workflows/pre-commit.yml` with `SKIP=super-linter,lint-traefik-swarm` and `SKIP_GIT_SIGNING_CHECK=1`.
- CalVer tagging: .github/workflows/calver-tag.yml

Bootstrap helpers:

```bash
# Bootstrap repo venv (cross-platform)
python -m scripts.dev.bootstrap_venv

# Setup Git commit signing (one-time, cross-platform)
.venv/bin/python -m scripts.devops.setup_git_signing

# Start work on an issue (required for issue-driven branches)
.venv/bin/python -m scripts.devops.start_issue_work --repo owner/name --issue 123
```

## Git Commit Signing

This repository requires all commits to be signed. The pre-commit hooks will verify signing configuration before allowing commits.

**One-time setup (cross-platform):**

```bash
.venv/bin/python -m scripts.devops.setup_git_signing
```

This script will:

- Create an SSH signing key if needed
- Configure Git for SSH commit signing
- Set up allowed signers file for local verification
- Provide instructions for registering the key on GitHub

**Verification:**

```bash
# Check current configuration
.venv/bin/python -m scripts.devops.setup_git_signing --check-only

# Verify a commit is signed
git log --show-signature -n 1
```

**Troubleshooting:**

If commits are unsigned in a PR, use the automated fix script:

```bash
.venv/bin/python -m scripts.github.fix_unsigned_commits --pr <NUMBER> --apply
```

See `docs/automation/runbooks/fix-unsigned-commits-in-pr.md` for detailed procedures.
