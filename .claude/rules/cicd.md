---
paths:
  - ".github/workflows/**"
  - ".github/actions/**"
---

# CI/CD Rules

- Orchestrator workflows MUST contain `uses:` only (never `run:` or `shell:`).
- Reusable workflows MUST use `workflow_call` with clear inputs/outputs.
- Composite actions: keep as thin wrappers, delegate to `scripts/`.
- Action pinning: MAJOR version pins only (e.g., `@v6`). Never pin to branches or exact minor/patch. Note: SHA pinning for third-party actions is preferred when supply-chain risk is a concern.
- Set `permissions: {}` at workflow level (zero-trust default). Declare explicit permissions per job.
- Never use `permissions: write-all` or omit permissions entirely.
- Prefer repo-provided validation scripts over inline checks.
- Source of truth: `.github/instructions/cicd.instructions.md`
