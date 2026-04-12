# Git Branching Standards

## Purpose

Define consistent branch naming, when branches are created, and how to clean up branches under squash-merge workflows.

## Branch naming

REQUIRE:

- Use issue-based branch naming with a developer-oriented type prefix:
  - `<type>/<number>-<scope>-short-slug`

Guidance:

- `<number>` MUST be the GitHub issue number.
- `<type>` SHOULD match the issue title type (see "Issue titles"). Prefer:
  - `docs`, `chore`, `feat`, `fix`, `refactor`, `test`, `security`
- `<scope>` SHOULD be a short area identifier (kebab-case). Prefer alignment with `area/*` labels.
- `short-slug` SHOULD be a short kebab-case description (3-6 words).
- Keep names stable and predictable. Avoid personal prefixes.

Examples:

- `docs/78-repo-standards-git-branching`
- `chore/83-precommit-bom-hook`

## Issue titles

REQUIRE:

- Use Conventional Commits style issue titles:
  - `type(scope): short summary`

Guidance:

- `type` SHOULD map to the repo's `type/*` labels where applicable:
  - Source of truth for `type/*` definitions: [../../.github/labels-hub.yml](../../.github/labels-hub.yml) (see the `# Types` section)
  - `docs` -> `type/docs`
  - `chore` -> `type/chore`
  - `feat` -> `type/feat`
  - `fix` -> `type/fix`
  - `refactor` -> `type/refactor`
  - `test` -> `type/test`
  - `security` -> `type/security`

- `scope` SHOULD reflect the impacted area (for example: `ci`, `docs`, `docker`, `python`, `security`, `network`, `traefik`).

Examples:

- `docs(repo-standards): define git branching standard`
- `chore(ci): fix auto-labeler false positives`

## Templates

Use the repo templates when creating issues and pull requests:

- Issues (work-package + incident-rca): [../../.github/ISSUE_TEMPLATE/work-package.yml](../../.github/ISSUE_TEMPLATE/work-package.yml)
- Pull requests: [../../.github/pull_request_template.md](../../.github/pull_request_template.md)

PR issue links (`Closes #...` / `Relates to #...`) can be kept deterministic with:

```bash
.venv/bin/python -m scripts.github.pr_sync_issue_links --close 123
```

## When to create a branch

REQUIRE:

- Create a branch only after the issue details have been fetched and the acceptance criteria are understood.

Rationale:

- Prevents creating branches for the wrong issue or outdated requirements.

## Versioning

This repository uses Calendar Versioning (CalVer). CI creates an
annotated tag on every squash merge to `main`, excluding the automated release commits produced by the workflow itself.

REQUIRE:

- CalVer tags apply to `main` only, after squash merge.
- Feature branches carry no version information.

Guidance:

- Tag format: `v{YYYY.0M.MICRO}` (e.g., `v2026.03.0`).
- `MICRO` resets to `0` each calendar month and increments per
  merge within a month.
- Each squash merge into `main` triggers CI to create an automated
  version-bump commit; the CalVer tag points to that release commit.

### Namespace separation

Branch names use a `type/` prefix (e.g., `docs/301-...`). Tags
use a `v` prefix (e.g., `v2026.03.0`). These namespaces do not
collide.

## Local cleanup after merge (squash merges)

This repository assumes squash merges. Squash merges do not preserve merge ancestry in a way that always satisfies git's "fully merged" checks.

REQUIRE:

- Fetch tags and updated main before cleanup:
  - `git fetch origin main --tags`
- Verify the branch contents are present on `origin/main` using a
  diff, not ancestry.
  - If `git diff --name-status origin/main..HEAD` is empty, treat the
    branch as already present in main.
- Delete the local branch after verification.

Guidance:

- If `git branch -d <branch>` refuses deletion due to "not fully merged", treat that as expected under squash merges.
  - Verify with a diff, then use `git branch -D <branch>` if appropriate.

## Remote cleanup

REQUIRE:

- The agent must not run `git push`.
- Remote branch deletion is a user operation.
