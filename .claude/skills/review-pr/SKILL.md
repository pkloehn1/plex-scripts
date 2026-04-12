---
name: review-pr
description: Triage PR review comments, run self-review for correctness/propagation/security/style, and fetch SonarCloud findings
---

# PR Review and Validation

Combines external comment triage, SonarCloud findings, and independent
self-review into a single workflow. Follow the prescribed analyze, recommend,
user-selects, implement workflow from `docs/repository-standards/devsecops-workflow.md`.

## Phase 1: Gather context

Detect the repo and PR from git context:

```bash
.venv/bin/python -m scripts.github.pr_overview --repo <owner/name>
```

If a PR number is not provided, detect from the current branch.

Collect the full diff and changed file list:

```bash
git diff --name-status origin/main...HEAD
git diff origin/main...HEAD
```

Read the linked issue (from the PR body `Closes #N`) to understand the
intent behind the changes.

## Phase 2: Read applicable standards

For each file type present in the diff, read the corresponding style guide
and path-scoped instructions before reviewing:

| File type      | Style guide                                                         | Instructions                                          |
| -------------- | ------------------------------------------------------------------- | ----------------------------------------------------- |
| Python         | `docs/repository-standards/style-guides/python-style-guide.md`      | `.github/instructions/python.instructions.md`         |
| Docker/YAML    | `docs/repository-standards/style-guides/docker-yaml-style-guide.md` | `.github/instructions/docker.instructions.md`         |
| Markdown       | `docs/repository-standards/style-guides/markdown-style-guide.md`    | (none)                                                |
| Shell          | `docs/repository-standards/style-guides/shell-style-guide.md`       | (none)                                                |
| CI/CD          | (none)                                                              | `.github/instructions/cicd.instructions.md`           |
| Infrastructure | (none)                                                              | `.github/instructions/infrastructure.instructions.md` |

Also read:

- `.github/instructions/code_review.instructions.md` — review focus areas
- `.github/instructions/development.instructions.md` — TDD and quality bar
- `docs/repository-standards/devsecops-workflow.md` — process compliance

## Phase 3: Fetch external review comments

List all unresolved Copilot review comments:

```bash
.venv/bin/python -m scripts.github.triage_review_comments \
  --repo <owner/name> --pr <NUMBER> --author-substring copilot
```

For other reviewers, change `--author-substring` accordingly.
Filter by file path with `--path` or content with `--contains`.

If no unresolved comments exist, skip to Phase 4.

## Phase 4: Fetch SonarCloud findings (when check fails)

Run this step only when the SonarCloud Code Analysis check has **failed**
(not when it is skipped or pending):

```bash
SONAR_TOKEN=$(op read "op://Private/SonarQube Cloud claude-code Token/credential") \
  .venv/bin/python -m scripts.github.sonarcloud_issues \
  --pull-request <NUMBER> --format summary
```

For detailed JSON output (needed for programmatic triage):

```bash
SONAR_TOKEN=$(op read "op://Private/SonarQube Cloud claude-code Token/credential") \
  .venv/bin/python -m scripts.github.sonarcloud_issues \
  --pull-request <NUMBER> --format json
```

Filter by severity or type as needed:

```bash
SONAR_TOKEN=$(op read "op://Private/SonarQube Cloud claude-code Token/credential") \
  .venv/bin/python -m scripts.github.sonarcloud_issues \
  --pull-request <NUMBER> --severities CRITICAL,BLOCKER --format summary
```

For duplication findings:

```bash
SONAR_TOKEN=$(op read "op://Private/SonarQube Cloud claude-code Token/credential") \
  .venv/bin/python -m scripts.github.sonarcloud_issues \
  --pull-request <NUMBER> --duplications --block-details --format summary
```

If SonarCloud check passed or is not present, skip to Phase 5.

## Phase 5: Self-review changes

Review every changed file against five categories. Use the `code-reviewer`
agent (subagent_type: `code-reviewer`) to validate style guide compliance
in parallel with your own analysis.

### 5a. Correctness

- Logic errors, off-by-one, missing edge cases
- Test assertions that are tautological or do not verify behavior
- Functions that silently swallow errors
- Type mismatches or missing type hints on new/modified functions

### 5b. Propagation

- Renames or moves reflected in all imports, docs, workflows, and config
- `sync-directives.yml` updated if synced files changed
- `pyproject.toml` updated if packages or test paths changed
- `README.md` or `scripts/github/README.md` updated if helper interfaces changed
- `.gitignore` updated if new generated/secret file patterns introduced

### 5c. Security

- No hardcoded secrets, tokens, passwords, or API keys
- No `:latest` Docker tags; no digest pinning
- Secrets accessed via Docker secrets or `op read`, never env vars in code
- No command injection vectors (unsanitized user input in `subprocess` calls)
- OWASP top 10 considerations for any web-facing code

### 5d. Convention compliance

- Delegate to the `code-reviewer` agent for style guide checks
- One-file-per-commit rule followed (Python exception: impl + test together)
- Commit messages follow conventional commit format
- `# pragma: no cover` only on `if __name__ == "__main__":` guards
- No inline suppressions (`# noqa`, `# nosec`, `# type: ignore`) without
  prior human approval

### 5e. Test coverage and quality

- New code has corresponding tests
- Tests verify behavior, not implementation details
- No mocking of internals that should be integration-tested
- 100% coverage maintained (check with `pytest --cov --cov-fail-under=100`)

## Phase 6: Compile and present findings

Merge findings from all sources (external comments, SonarCloud, self-review)
into a single table following the format defined in
`.github/instructions/code_review.instructions.md` § "Review findings format".

Group related findings when they share a root cause.
Discard findings that are purely stylistic preferences not backed by style guides.

Wait for user selection before implementing any fixes.

## Phase 7: Post review to GitHub

After user reviews the findings summary, post self-review findings as an
atomic PR review using `create_pr_review`. This documents the findings on
the PR itself.

Dry-run first (safe-by-default):

```bash
.venv/bin/python -m scripts.github.create_pr_review \
  --repo <owner/name> --pr <NUMBER> \
  --body "Self-review: N findings (X errors, Y warnings, Z info)" \
  --event COMMENT \
  --comments-json '[{"path": "<file>", "line": <N>, "body": "[SEVERITY] <description>"}]'
```

After user confirms, submit:

```bash
.venv/bin/python -m scripts.github.create_pr_review \
  --repo <owner/name> --pr <NUMBER> \
  --body "Self-review: N findings (X errors, Y warnings, Z info)" \
  --event COMMENT \
  --comments-json '[{"path": "<file>", "line": <N>, "body": "[SEVERITY] <description>"}]' \
  --apply
```

For multi-line findings, use `start_line` and `line` to highlight the range:

```json
[
  {
    "path": "scripts/foo.py",
    "start_line": 10,
    "line": 15,
    "body": "[WARNING] Convention — Missing type hints on new function parameters"
  }
]
```

## Phase 8: Implement and resolve

After user selects options for ERROR/WARNING findings:

1. Implement fixes following one-file-per-commit rule (Python exception: impl + tests together).
2. Reply and resolve review comments in bulk:

```bash
.venv/bin/python -m scripts.github.triage_review_comments \
  --repo <owner/name> --pr <NUMBER> --author-substring copilot \
  --replies-json '[{"comment_id": <ID>, "body": "Fixed in <SHA>. <description>"}]'
```

SonarCloud findings resolve automatically on re-scan after push.

## Phase 9: Sync PR body

After pushing fixes:

```bash
.venv/bin/python -m scripts.github.pr_upsert \
  --repo <owner/name> --number <NUMBER> --auto-summary --issue <ISSUE>
```

If no findings require fixes, report "Validation passed — no issues found."
