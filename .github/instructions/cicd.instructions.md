---
applyTo: ".github/workflows/**,.github/actions/**"
---

# CI/CD Instructions

Path-specific instructions for CI/CD workflow and action files.

## Workflow Architecture

Orchestrator workflows:

- MUST contain `uses:` only
- NEVER use `run:` or `shell:` directly in orchestrators
- Delegate logic to reusable workflows or scripts

Reusable workflows:

- MUST use `workflow_call`
- MUST encapsulate a single responsibility
- MUST define clear inputs/outputs

Composite actions:

- Keep as thin wrappers
- Prefer calling scripts under `scripts/` instead of embedding logic

## Action Pinning

REQUIRE:

- MAJOR version pins only (e.g. `@v6`, `@v8`) — use the latest major version
  available for each action

NEVER:

- Pin to branches (`@main`, `@master`)
- Pin to exact minor/patch versions (`@v4.1.2`)

## GitHub Token Permissions

See: `docs/repository-standards/style-guides/github-actions-style-guide.md`

REQUIRE:

- Set `permissions: {}` at the workflow level (zero-trust default)
- Declare explicit `permissions:` on every job (job-level grants)
- Grant only the scopes each job actually needs

NEVER:

- Use `permissions: write-all` or omit `permissions:` entirely
- Duplicate the same permission at both workflow and job level with non-empty
  values

## Known Workflows

- `calver-tag.yml` — on pushes to `main`:
  - Creates a CalVer tag (`v{YYYY.0M.MICRO}`) via the GitHub API (`scripts.github.create_tag`)
  - Publishes a GitHub Release with git-cliff release notes
  - Skips if the head commit message contains `chore(release):` or `[skip ci]`
  - Does not commit to `main`
  - Requires `contents: write` at the job level

## Validation

- Prefer repo-provided validation scripts over re-implementing checks inline
