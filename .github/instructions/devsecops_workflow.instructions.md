---
applyTo: "**"
---

# DevSecOps Workflow (SSOT)

This repository's single source of truth (SSOT) for "start work on issue #X" is:

- `docs/repository-standards/devsecops-workflow.md`

## Non-negotiables

- Keep 1 issue = 1 branch/PR whenever feasible.
- Do not run `git push` (user owns all remote sync operations).
- For GitHub operations (issues/PRs/comments/threads/rulesets), use the helper modules under `scripts/github/`:

```bash
# Preferred on Linux nodes (repo virtualenv):
.venv/bin/python -m scripts.github.<module> ...

# Fallback when a venv is not available:
python3 -m scripts.github.<module> ...
```

- Do not use `python` on Linux nodes; it may not be installed or may not point to Python 3.

- Assume squash merges; verify merges using diffs, not git ancestry.
- CalVer tagging is automated: every squash merge to `main` triggers `calver-tag.yml`. Do not create version tags manually.

## Start work on issue #X (ordered steps)

Follow this sequence exactly:

1. Fetch the GitHub issue details (title, requirements, acceptance criteria).
  Issue titles MUST follow conventional commit format (`type(scope): short summary`) per `docs/repository-standards/git-branching.md`.
2. Create branch using `scripts.devops.start_issue_work`. Do not manually construct branch names.
3. Implement the change and validate locally (lint/tests as applicable).
4. Wait for the user to push the branch (the agent must never run `git push`).
5. Create the PR (ready-for-review) via `scripts.github.pr_upsert` with `--auto-summary --issue <NUMBER>` as soon as the user has pushed the branch.
  Always use `--auto-summary`; never use `--body` or `--body-file` for PR creation.
  Do not defer to end of implementation — early PRs trigger CI checks
  (SonarQube, Super-Linter) that the IDE cannot reliably catch locally.

## Templates

- Work packages: `.github/ISSUE_TEMPLATE/work-package.yml`
- Pull requests: `.github/pull_request_template.md`

## PR discipline

- Follow the PR template in `.github/pull_request_template.md`.
- Create PRs as ready-for-review. Create early (after first push) to trigger CI checks.
- Rely on pre-commit hooks (fired automatically during `git commit`) and CI checks for validation. Do not run `pre-commit run` as a separate step.
- **Review comments**: follow the structured analyze → recommend → user-selects → implement process in `docs/repository-standards/devsecops-workflow.md` § "PR review comment handling".

## Dependabot PRs

- Dependabot image update PRs bypass the standard issue-driven workflow.
- Follow `docs/automation/runbooks/dependabot-image-update-verification-sop.md` instead.

## Control tool bypass

Never bypass, disable, or suppress any linter, security scanner, pre-commit hook, or control tool without explicit human approval.
This includes `--no-verify`, `SKIP=<hook>`, inline suppressions (`# noqa`, `# nosec`, `# type: ignore`),
and linter config changes that loosen rules.
When a control tool fails repeatedly (>2 attempts), escalate to the user with error details.

## Change management

- See `.github/copilot-instructions.md` "Git Safety" section for atomic commits requirement (one file per commit).
- **Python exception**: implementation files and their corresponding test files MUST be committed together to maintain 100% test coverage.
- Prefer small, reviewable diffs; avoid speculative refactors.
