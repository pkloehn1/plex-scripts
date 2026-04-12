---
paths:
  - "**/*.sh"
---

# Shell Script Rules

- Use `#!/usr/bin/env bash` for new bash scripts.
- Enable strict mode: `set -Eeuo pipefail`.
- Quote variables unless intentional word splitting is required.
- Validate required env vars: `: "${VAR:?VAR is required}"`.
- Scripts MUST be idempotent (safe to run multiple times).
- Use `[[ ... ]]` for conditionals in bash scripts (not `[ ... ]`).
- Use functions for reusable steps. Keep functions short and focused.
- Prefer `printf` over `echo` for predictable output formatting.
- Shell changes must pass shellcheck via Super-Linter.
- Source of truth: `docs/repository-standards/style-guides/shell-style-guide.md`
