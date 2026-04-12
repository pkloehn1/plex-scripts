---
applyTo: "**/*.py,**/*.sh,**/*.ps1"
---

# Development Instructions

Path-specific instructions for code and automation scripts.

## Change Scope

- Prefer the smallest diff that satisfies requirements.
- Preserve existing patterns and naming.

## Test-Driven Development

REQUIRE:

- Write tests before implementation
- Run tests to confirm they fail
- Implement minimal code to pass
- Refactor with passing tests
- Maintain 100% test coverage across the repository
- Prefer the narrowest validation that proves the change

NEVER:

- Skip tests to meet deadlines
- Commit code without passing tests

## Git Workflow

REQUIRE:

- Conventional commit messages
- Feature branches for changes
- PR review before merge

Protected operations (user approval required):

- Push to remote
- Force push
- Branch deletion
- PR merge

## Code Quality

REQUIRE:

- Linting passes before commit
- Format validation (language-specific formatter)
- No hardcoded secrets or credentials

ENFORCE:

- Single responsibility per module
- Files under 500 lines
- Functions under 50 lines

## Security

- Never commit secrets.
- Prefer least-privilege defaults.

## Script Reliability

Shell (`.sh`):

- Use strict mode (`set -Eeuo pipefail`), quote variables.
- Scripts MUST be idempotent (safe to run multiple times).

PowerShell (`.ps1`):

- Use `Set-StrictMode -Version Latest` where compatible.
- Use `try/catch` for error handling; avoid `Write-Host` for functional output.
- Scripts MUST be idempotent (safe to run multiple times).

## Documentation

REQUIRE:

- Docstrings for public functions
- Type hints where language supports
- README for modules with external interfaces
