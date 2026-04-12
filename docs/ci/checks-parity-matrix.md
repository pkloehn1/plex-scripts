# Pre-commit and CI Parity Matrix (Windows, Linux, GitHub Actions)

## Purpose

Provide a single source of truth (SSOT) for ensuring that local pre-commit
checks on Windows and Linux match GitHub Actions checks and use the same
configuration files wherever possible.

## Scope

- Windows pre-commit and commit actions (local)
- Linux pre-commit and commit actions (local)
- GitHub Actions checks

Windows and Linux must run the same pre-commit hooks from the same
configuration. Differences are only allowed where the execution shell differs
(PowerShell vs bash) while using the same underlying scripts and configuration
files.

## Sources of truth

- Pre-commit hooks: `.pre-commit-config.yaml`
- Local Super-Linter runner: `scripts/linting/run_super_linter.py`
- GitHub Actions:
  - `./.github/workflows/pre-commit.yml`
  - `./.github/workflows/super-linter.yml`
  - `./.github/workflows/pytest-coverage.yml`
- Shared configs:
  - `.editorconfig`
  - `./.github/linters/.jscpd.json`
  - `./.github/linters/.markdownlint.json`
  - `./.github/linters/.ruff.toml`
  - `./.github/linters/.markdownlint.yml`
  - `./.github/linters/.yaml-lint.yml`

## Parity matrix

Legend:

- Local hook (Windows) = pre-commit hook id on Windows
- Local hook (Linux) = pre-commit hook id on Linux
- CI check = GitHub Actions workflow + job (or required context)
- Config files = repo files that define or tune behavior (use `none` if default)
- Parity status = `aligned` or `gap`

| Check | Local hook (Windows) | Local hook (Linux) | CI check | Config files | Parity status |
| --- | --- | --- | --- | --- | --- |
| Repo location | check-repo-location | check-repo-location | Pre-commit Hooks / Run pre-commit | `scripts/testing/hooks/check_repo_location.py` | aligned |
| Prevent unintended deletions | prevent-unintended-deletions-pre + prevent-unintended-deletions-post | prevent-unintended-deletions-pre + prevent-unintended-deletions-post | Pre-commit Hooks / Run pre-commit | `scripts/testing/hooks/prevent_unintended_deletions.py` | aligned |
| Repo layout invariants | check-repo-layout | check-repo-layout | Pre-commit Hooks / Run pre-commit | `scripts/testing/hooks/check_repo_layout.py` | aligned |
| Documentation invariants | check-doc-invariants | check-doc-invariants | Pre-commit Hooks / Run pre-commit | `scripts/testing/hooks/check_doc_invariants.py` | aligned |
| Workflow install patterns | check-workflow-install-patterns | check-workflow-install-patterns | Pre-commit Hooks / Run pre-commit | `scripts/testing/hooks/check_workflow_install_patterns.py` | aligned |
| Git signing configured | check-git-signing | check-git-signing | Pre-commit Hooks / Run pre-commit (SKIP_GIT_SIGNING_CHECK=1) | `scripts/testing/hooks/check_git_signing.py` | gap |
| End-of-file fixer | end-of-file-fixer | end-of-file-fixer | Pre-commit Hooks / Run pre-commit | none | aligned |
| Mixed line ending | mixed-line-ending | mixed-line-ending | Pre-commit Hooks / Run pre-commit | none | aligned |
| Trailing whitespace | trailing-whitespace | trailing-whitespace | Pre-commit Hooks / Run pre-commit | none | aligned |
| UTF-8 BOM fixer | fix-byte-order-marker | fix-byte-order-marker | Pre-commit Hooks / Run pre-commit | none | aligned |
| YAML syntax | check-yaml | check-yaml | Pre-commit Hooks / Run pre-commit | none | aligned |
| YAML strict lint | yamllint | yamllint | Pre-commit Hooks / Run pre-commit + Super-Linter | `./.github/linters/.yaml-lint.yml` | aligned |
| Large file guard | check-added-large-files | check-added-large-files | Pre-commit Hooks / Run pre-commit | none | aligned |
| Merge conflict markers | check-merge-conflict | check-merge-conflict | Pre-commit Hooks / Run pre-commit | none | aligned |
| Executables have shebangs | check-executables-have-shebangs | check-executables-have-shebangs | Pre-commit Hooks / Run pre-commit | none | aligned |
| Shebang scripts executable | check-shebang-scripts-are-executable | check-shebang-scripts-are-executable | Pre-commit Hooks / Run pre-commit | none | aligned |
| Docker Compose linter | dclint | dclint | Pre-commit Hooks / Run pre-commit | none | aligned |
| GitHub Actions architecture | validate-github-actions-architecture | validate-github-actions-architecture | Pre-commit Hooks / Run pre-commit | `scripts/testing/validate_github_actions_architecture.py` | aligned |
| Markdown heading numbers | validate-heading-numbers | validate-heading-numbers | Pre-commit Hooks / Run pre-commit | `scripts/linting/validate_heading_numbers.py` | aligned |
| Mermaid diagram render | check-mermaid-diagrams | check-mermaid-diagrams | Pre-commit Hooks / Run pre-commit | `scripts/linting/check_mermaid_diagrams.py` | aligned |
| Filename conventions | check-filename-conventions | check-filename-conventions | Pre-commit Hooks / Run pre-commit | `scripts/linting/check_filename_conventions.py` | aligned |
| Bound port interfaces | check-bound-ports | check-bound-ports | Pre-commit Hooks / Run pre-commit | `scripts/linting/check_bound_ports.py` | aligned |
| Compose network mode conflicts | check-compose-network-mode-conflicts | check-compose-network-mode-conflicts | Pre-commit Hooks / Run pre-commit | `scripts/linting/check_compose_network_mode_conflicts.py` | aligned |
| Bash conditional tests | lint-bash-conditional-tests | lint-bash-conditional-tests | Pre-commit Hooks / Run pre-commit | `scripts/linting/check_bash_test_syntax.py` | aligned |
| Cognitive complexity | check-cognitive-complexity | check-cognitive-complexity | Pre-commit Hooks / Run pre-commit | `scripts/linting/check_cognitive_complexity.py` | aligned |
| Short identifier names | check-short-identifier-names | check-short-identifier-names | Pre-commit Hooks / Run pre-commit | `scripts/linting/check_short_identifier_names.py` | aligned |
| EditorConfig compliance | editorconfig-checker | editorconfig-checker | Pre-commit Hooks / Run pre-commit + Super-Linter | `.editorconfig` | aligned |
| Python lint (Ruff) | ruff | ruff | Pre-commit Hooks / Run pre-commit + Super-Linter | `pyproject.toml` (standalone), `./.github/linters/.ruff.toml` (Super-Linter) | aligned |
| Python format (Ruff) | ruff-format | ruff-format | Pre-commit Hooks / Run pre-commit + Super-Linter | `pyproject.toml` (standalone), `./.github/linters/.ruff.toml` (Super-Linter) | aligned |
| Shell formatting | shfmt | shfmt | Pre-commit Hooks / Run pre-commit + Super-Linter | none | aligned |
| Super-Linter (local) | super-linter | super-linter | Super-Linter / Lint Code Base | `scripts/linting/run_super_linter.py`, `.editorconfig`, `./.github/linters/*` | gap |
| Pytest (manual) | pytest (manual stage only) | pytest (manual stage only) | none | `pyproject.toml` | gap |

## Alignment targets

- Local Windows and Linux must continue to use identical hook definitions from
  `.pre-commit-config.yaml`.
- CI runs the full pre-commit hook suite with:
  - `SKIP=super-linter` (covered by dedicated workflows)
  - `SKIP_GIT_SIGNING_CHECK=1` (CI cannot configure commit signing)
- Where `Parity status` is `gap`, either:
  - add the check to GitHub Actions with the same config, or
  - add a local hook equivalent when a CI check exists without a local hook.

## Super-Linter configuration parity (CI vs local)

The table below captures explicit differences and bypasses that affect whether
local runs can pass code that CI would reject, or vice versa. Items marked as
`gap` require a deliberate decision to keep, tighten, or remove.

| Aspect | Local (pre-commit runner) | CI (GitHub Actions) | Impact | Status |
| --- | --- | --- | --- | --- |
| Image tag | `ghcr.io/super-linter/super-linter:v8` (default) | `ghcr.io/super-linter/super-linter:v8` | Same linter version | aligned |
| Default branch | Resolved from repo (or `SUPER_LINTER_DEFAULT_BRANCH`) | `origin/${{ github.event.repository.default_branch }}` | Same target when remote refs exist | aligned |
| Scope | `VALIDATE_ALL_CODEBASE=false` unless default branch ref missing | `VALIDATE_ALL_CODEBASE=false` | Local becomes stricter when branch ref missing | gap |
| Staged-file blindness | `RUN_LOCAL=true` sets `GITHUB_SHA=HEAD` (last commit); `git diff-tree` cannot see staged-only files | N/A (commit exists when CI runs) | New files on first branch commit are invisible to local Super-Linter; mitigated by standalone pre-commit hooks | gap |
| Ruff config | `./.github/linters/.ruff.toml` (sync copy of `pyproject.toml`) | `./.github/linters/.ruff.toml` | Same config; `pyproject.toml` is source of truth | aligned |
| JSCPD config | Auto-sets `JSCPD_LINTER_RULES` if not already set | Explicit `JSCPD_LINTER_RULES` set | Same config path, consistent rules | aligned |
| Local-only excludes | Sets `FILTER_REGEX_EXCLUDE` for `.venv`, `.tox`, caches when not specified | Not set | Local can skip scanning dev-only artifacts | gap |

## Ruff configuration sync

Super-Linter passes `--config` to ruff, which bypasses `pyproject.toml`
discovery. The file `.github/linters/.ruff.toml` is a sync copy of
`pyproject.toml` `[tool.ruff]` settings for Super-Linter consumption. When
ruff configuration changes in `pyproject.toml`, update `.ruff.toml` to match.

## Super-Linter configured rules

This table enumerates the Super-Linter validators enabled in the workflow and
the config sources they rely on. Use it to confirm each validator enforces the
intended repo standard.

| Validator | Purpose | Config source | Notes |
| --- | --- | --- | --- |
| GitHub Actions | Lint GitHub Actions workflows | `./.github/workflows/*.yml` | Uses Super-Linter defaults |
| Markdown | Markdown linting | `./.github/linters/.markdownlint.yml`, `./.github/linters/.markdownlint.json` | MD013 line length 200, MD024 duplicate headings, MD033 inline HTML, MD041 first-line heading |
| YAML | YAML linting | `./.github/linters/.yaml-lint.yml` | Line length 120, tightens indentation/truthy |
| JSCPD | Duplicate code detection | `./.github/linters/.jscpd.json` | Ignores dev caches and test fixtures |
| Bash | ShellCheck for Bash scripts | none | Uses Super-Linter defaults |
| Bash executable | Enforce executable bit on shell scripts | none | Uses Super-Linter defaults |
| Shell formatting | shfmt formatting for shell scripts | none | Uses Super-Linter defaults |
| PowerShell | PSScriptAnalyzer for PowerShell | none | Uses Super-Linter defaults |
| JSON | JSON linting | none | Uses Super-Linter defaults |
| JSONC | JSONC linting | none | Uses Super-Linter defaults |
| EditorConfig | Validate EditorConfig compliance | `.editorconfig` | Applies to tracked files |
| Checkov | IaC security scanning | none | Enabled; expect findings in compose YAML |
| Env files | `.env` file linting | none | Applies to `.env` and templates |
| Gitleaks | Secrets scanning | none | Uses Super-Linter defaults |
| Python (Ruff) | Ruff linting for Python | `./.github/linters/.ruff.toml` | Sync copy of `pyproject.toml [tool.ruff]` |
| Python (Ruff format) | Ruff formatting for Python | `./.github/linters/.ruff.toml` | Sync copy of `pyproject.toml [tool.ruff.format]` |
