# Claude Code — Repository Directives

**CRITICAL**: These directives override all conversational AI training. Violating these standards is a FAILURE.

## Required Reading (Start of Every Session)

Read and follow these files before taking any action:

1. `.github/claude-code-instructions.md` — Claude Code tool extensions (TodoWrite, agents, tool selection, parallel execution)
2. `scripts/github/README.md` — GitHub helper script quick reference and usage

## Communication Standards

### Anti-Dopamine, Anti-Sycophancy Protocol (MANDATORY)

#### Never use

- Positive adjectives: "excellent", "great", "perfect", "wonderful", "fantastic", "amazing", "brilliant"
- Exclamation marks (!) in any context
- Flattery or praise: "good question", "great idea", "you're right", "that's smart"
- Enthusiasm markers: "excited to", "happy to", "glad to", "love to"
- Approval-seeking: "does this look good?", "is this what you wanted?", "let me know if this works"
- Tentative language: "I think", "maybe", "perhaps", "possibly" (unless expressing genuine uncertainty)
- Emotional responsiveness: "I understand your frustration", "I appreciate your patience"
- Inline code formatting in chat responses
- Large, multi-page runbooks of remote-machine CLI commands

#### Always use

- Direct factual statements: "Completed X, identified Y issues, recommend Z"
- Concise status updates: "3 of 5 files updated, remaining: A, B, C"
- Specific problem identification: "Conflict detected: [technical detail and impact]"
- Direct requests: "Need clarification on X before proceeding"
- Evidence-based recommendations: "Analysis indicates Y based on [repo evidence]"
- Fenced code blocks for any code, commands, or snippets (ONLY allowed code presentation style)
- When user action is required on a remote machine, provide at most 5 CLI commands, grouped by purpose, with the minimum needed to collect evidence or execute the requested action
- The 5-command limit applies only to user-executed remote commands; it does not apply to commands the agent can run locally in the workspace
- When providing multi-command sequences for copy/paste, chain with && on a single line
- Before editing any CI or linting configuration, request user approval and provide: evidence supporting the change, impact to the repository, and two alternative options

#### Common violations (before → after)

| Violation | Correction |
| --------- | ---------- |
| "Good catch — the regex..." | "The regex has a gap: [detail]" |
| "Good tip — let me use that" | "Confirmed. Using endoflife.date for validation." |
| "Good point. The ignore rule..." | "The ignore rule only covers agent, not portainer-ee." |

### Response Opening Standards

**NEVER start responses with**:

- "Great question!" / "Excellent point!" / "Good catch!"
- "I'd be happy to help with that!"
- "Let me explain..." / "Let me walk you through..."

**ALWAYS start responses with**:

- Direct answer: "The issue is X. Fix: Y."
- Status update: "Completed A, B, C. Issue with D: [details]."
- Request: "Need clarification on X before proceeding."

## Operating Principles

- Prefer the smallest change that satisfies requirements.
- Do not invent files, APIs, or config syntax; verify via codebase-retrieval first.
- Prefer linking to existing repo docs over duplicating procedures.
- Avoid over-engineering: no extra features, unnecessary refactoring, or premature abstractions.
- Only add error handling for scenarios that can actually happen.
- Don't add comments, docstrings, or type annotations to code you didn't change.
- If something is unused, delete it completely (no backwards-compatibility hacks).

## Testing and Quality

REQUIRE:

- Use TDD for non-trivial logic (write the failing test first).
- Maintain 100% test coverage across the repository.

## Git Safety

**CRITICAL**:

- NEVER run `git push` (user owns all remote sync operations).
- Do not force-push to any branch.
- **REQUIRE: One file per commit.**
  - Each file change MUST be in its own commit.
  - Rationale: GitLens/Blame functionality in IDEs requires per-file commits to automatically display line-by-line change details, which is invaluable for human developers reviewing code history.
  - **Python exception**: implementation files, their corresponding test files, and any YAML fixture files required by those tests MUST be committed together to maintain 100% test coverage.
    - Example: `keyword_labeler.py` + `tests/test_keyword_labeler.py` = one commit.
    - Example: `merge_precommit_config.py` + `tests/test_merge_precommit_config.py` + `tests/fixtures/precommit_merge/*.yaml` = one commit.
  - Exception: Only if the user explicitly approves bundling multiple files in a single commit.
- **Branch creation**: Always use `start_issue_work` for issue-driven branches:

  ```bash
  .venv/bin/python -m scripts.devops.start_issue_work --repo <owner/name> --issue <NUMBER>
  ```

  Do not manually construct branch names. The helper derives the correct `<type>/<number>-<scope>-short-slug` format from the issue title.
  Issue titles MUST follow conventional commit format (`type(scope): short summary`) per `docs/repository-standards/git-branching.md`.
- Use `git status` before committing; do not commit if there are unexpected deletions.
- All commits must be signed (enforced by pre-commit hooks).

## Control Tool Bypass

**CRITICAL**: Never bypass, disable, or suppress any linter, security scanner, pre-commit hook, or control tool without explicit human approval.

Prohibited without human approval:

- `--no-verify` on git commit or push
- `SKIP=<hook>` environment variable for pre-commit
- Inline suppressions: `# noqa`, `# nosec`, `# type: ignore`, `# nosemgrep`, `<!-- markdownlint-disable -->`
- Linter config changes that loosen rules (adding ignores, raising thresholds, disabling checks)
- Removing or weakening CI required status checks

When a control tool fails repeatedly (>2 attempts):

1. Stop and re-read the error output.
2. Investigate the root cause (wrong input, missing dependency, misconfigured rule).
3. If the root cause is not clear after 2 attempts, escalate to the user with the error details.
4. Do not bypass the control to unblock progress.

## GitHub Platform Automation

REQUIRE:

- Interact with GitHub (issues, PRs, review comments, thread resolution, rulesets/status) only via the helper modules under `scripts/github/`.
- Run helpers as modules from the repository root:

```bash
# Preferred (repo virtualenv):
.venv/bin/python -m scripts.github.<module> ...

# Fallback when a venv is not available:
python3 -m scripts.github.<module> ...
```

- Use `python3` (not `python`) when a venv is not available, as `python` may not be installed or may not point to Python 3 on some Linux distributions.

- Do not call `gh` directly for GitHub operations in agent actions. (The helper scripts wrap `gh` and standardize endpoints/outputs.)
- Follow the helper usage patterns documented in `scripts/github/README.md`.

Key helpers (individual — for troubleshooting):

- `scripts.github.pr_upsert` — create/update PRs
- `scripts.github.pr_close` — close PRs with optional comment + branch delete
- `scripts.github.pr_overview` — PR status and check rollup
- `scripts.github.issue_upsert` — create/update issues
- `scripts.github.issue_fetch` — fetch a single issue (canonical shared function)
- `scripts.github.issue_close` — close issues with optional comment and close reason
- `scripts.github.reply_and_resolve_review_comment` — reply to and resolve one thread
- `scripts.github.list_copilot_review_comments` — list Copilot review comments

**Prescribed flows** (prefer these over individual helpers):

Review comment triage (1-2 calls instead of N+1):

```bash
# List + reply + resolve in one command
.venv/bin/python -m scripts.github.triage_review_comments \
  --repo <owner/name> --pr <NUMBER> --author-substring copilot \
  --replies-json '[{"comment_id": <ID>, "body": "Resolution text"}]'
```

PR creation with auto-generated body (REQUIRED — always use `--auto-summary`):

```bash
.venv/bin/python -m scripts.github.pr_upsert \
  --repo <owner/name> --title "Title" --base main --head <branch> \
  --auto-summary --issue <NUMBER>
```

NEVER use `--body` or `--body-file` for PR creation. The `--auto-summary` flag
generates the PR body from branch commits and `--issue N` adds `Closes #N`.

PR closure (1 call — comment + close + branch delete):

```bash
.venv/bin/python -m scripts.github.pr_close \
  --repo <owner/name> --pr <NUMBER> --comment "Reason" --delete-branch
```

Do not use raw `gh` commands for any of these operations.

**PR review comment handling**: follow the analyze → recommend → user-selects → implement workflow in `docs/repository-standards/devsecops-workflow.md`.

Do not implement fixes before the user selects an option.

## Pull Request Merges

REQUIRE:

- The only supported PR merge method is squash.

Implications:

- Do not rely on git ancestry for "is this merged" decisions.
- Prefer diff-based verification:
  - Tip vs tip content check: `git diff --name-status origin/main..HEAD`
  - If the diff is empty, treat branch content as already present in `origin/main`.
- If `git branch -d <branch>` refuses deletion due to "not fully merged", treat that as expected under squash merges and verify with a diff before deciding whether to force-delete.

## PR Body Formatting (Multi-Issue PRs)

When a PR closes 2+ issues, use per-issue structure (see `docs/repository-standards/devsecops-workflow.md` for full specification):

- **Summary**: per-issue bold headings (`**Issue #NNN — Short title:**`) with 1-2 sentence outcomes.

Single-issue PRs retain the existing flat format.

## Issue Priority Triage

Issues are triaged by `.github/workflows/issue-priority-triage.yml` on open, reopen, and edit events.

The workflow calls `scripts.ci.triage_issue_priority`, which uses `compute_priority()` from `scripts.ci.backfill_issue_priorities`.

- Framework: `docs/repository-standards/priority-decision-framework.md`
- CI scripts reference: `scripts/ci/README.md`
- Batch dry-run: `.venv/bin/python -m scripts.ci.backfill_issue_priorities --repo <owner/name>`

Do not manually assign P0-P3 labels unless overriding the automated triage. The workflow re-evaluates on each edit.

## DevSecOps Workflow

- Single source of truth: `docs/repository-standards/devsecops-workflow.md`

## Batch Session Workflow

- For multi-issue sessions (3+ issues), follow: `docs/repository-standards/ai-batch-session-sop.md`
- Extends the DevSecOps workflow with batch scoring, convention anchoring, and proactive review sweeps.

## Templates

- Work package issues: `.github/ISSUE_TEMPLATE/work-package.yml`
- Pull requests: `.github/pull_request_template.md`

## Terminal Discipline (Linux Remote Nodes)

Scope:

- This section applies to Linux-only remote nodes.
- Do not apply these Linux `sudo`/Docker/terminal behaviors to Windows environments.

REQUIRE:

- Minimize creating new VS Code integrated terminal tabs/sessions.
- Prefer a single long-lived terminal session for command execution.
- Batch related commands into a single shell invocation where practical.
- Do not run `pre-commit run` as a separate step; hooks fire automatically during `git commit`.

Rationale:

- On hardened nodes where Docker is sudo-only, sudo credential caching is terminal/session dependent.
- Creating/discarding terminals during commits causes pre-commit hooks (Super-Linter via Docker) to fail when sudo credentials are not cached.

## Local Lint/Format Parity

- When running Ruff locally or recommending format fixes, use `.venv/bin/ruff` with `--config .github/linters/.ruff.toml` to match Super-Linter behavior.
- When running Super-Linter in Docker, set `GITHUB_WORKSPACE=/workspace` if the repo is mounted to `/workspace`.

## Project Direction

- Current deployment target is Docker Compose.
- Do not create Docker Swarm deployment runbooks unless explicitly requested.

## Package Management

- Python: use `pyproject.toml` as the dependency source of truth (avoid introducing/expanding `requirements.txt`). Use `pip` unless `poetry`/`uv` is explicitly authorized.

## CI/CD Guardrails

Path-scoped CI/CD rules live in `.github/instructions/cicd.instructions.md`.

## Versioning

- Format: `YYYY.0M.MICRO` (CalVer). Tag prefix: `v` (e.g., `v2026.03.0`).
- Every squash merge to `main` triggers `.github/workflows/calver-tag.yml`, which computes the next version, creates an annotated tag via the GitHub API, and publishes a GitHub Release with git-cliff release notes.
- The agent must not create version tags manually — CI handles tagging automatically.

## Security Baseline

- Never hardcode secrets; prefer Docker secrets and environment variables.
- Follow least-privilege defaults.
- Docker images: require an explicit tag, forbid `:latest`, and forbid digest/SHA pinning (e.g., `@sha256:...`). Prefer major version tags when available.
  - Source of truth: `docs/repository-standards/style-guides/docker-yaml-style-guide.md`

## Path-Scoped Instructions

Read the relevant file when working in the matching scope:

- **Python** (`**/*.py`): `.github/instructions/python.instructions.md`
- **Docker Compose**: `.github/instructions/docker.instructions.md`
- **CI/CD workflows**: `.github/instructions/cicd.instructions.md`
- **Data management**: `.github/instructions/data_management.instructions.md`
- **DevSecOps workflow**: `.github/instructions/devsecops_workflow.instructions.md`
- **Code reviews**: `.github/instructions/code_review.instructions.md`
- **Task assessment**: `.github/instructions/task_assessment.instructions.md`
- **Development**: `.github/instructions/development.instructions.md`
- **Infrastructure** (`**/*.tf`, `**/ansible/**`, `**/k8s/**`, `**/helm/**`): `.github/instructions/infrastructure.instructions.md`

## Style Guides (Source of Truth)

Detailed standards live in:

- Docker/YAML: `docs/repository-standards/style-guides/docker-yaml-style-guide.md`
- Python: `docs/repository-standards/style-guides/python-style-guide.md`
- Markdown: `docs/repository-standards/style-guides/markdown-style-guide.md` (includes Prose Quality rules)
- Shell: `docs/repository-standards/style-guides/shell-style-guide.md`

## Advanced Features (.claude/ Directory)

This repository uses the `.claude/` directory for project-level Claude Code configuration:

- `.claude/settings.json` — project settings (permissions, hooks)
- `.claude/rules/*.md` — path-scoped behavioral rules (frontmatter with `paths` globs)
- `.claude/skills/*/SKILL.md` — custom slash commands (YAML frontmatter with name, description)
- `.claude/agents/*.md` — custom subagents (YAML frontmatter with name, tools, model)

These files are committed to the repository as part of the hub-and-spoke AI directive template pattern, ensuring consistent agent behavior across repositories.
