# Shell Script Style Guide

## Purpose

Normative rules for shell scripts in this repository.

## Shell Choice

REQUIRE:

- Use `#!/usr/bin/env bash` for new bash scripts unless a platform constraint requires otherwise.

## Safety and Error Handling

REQUIRE:

- Enable strict mode at the top of scripts:

```bash
set -Eeuo pipefail
```

- Quote variables unless intentional word splitting is required.
- Validate required environment variables using parameter expansion:

```bash
: "${VAR:?VAR is required}"
```

NEVER:

- Rely on implicit globals or unset variables.

## Idempotency

REQUIRE:

- Scripts MUST be idempotent (safe to run multiple times).
- Check current state before making changes.
- Avoid destructive operations unless guarded (explicit confirmation or a clearly documented safety switch).

## Portability

REQUIRE:

- Prefer POSIX-compatible utilities unless bash features are required.
- When bash-specific features are used, keep scripts explicitly bash.

## Conditionals

REQUIRE:

- In bash scripts, use `[[ ... ]]` instead of `[ ... ]` for conditional tests.

Notes:

- `[[ ... ]]` is bash-specific; do not use it in POSIX `sh` scripts.
- If a script must be POSIX `sh`, keep it explicitly `#!/bin/sh` and use `[ ... ]`.

## Linting

REQUIRE:

- Shell changes MUST pass repo linting (Super-Linter runs `shellcheck`).
- Fix issues rather than suppressing warnings.

## Structure

REQUIRE:

- Use functions for reusable steps.
- Keep functions short and focused.

PREFER:

- `printf` for predictable output formatting.

## See Also

- [Documentation Standards](../documentation-standards.md)
