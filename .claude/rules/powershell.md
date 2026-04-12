---
paths:
  - "**/*.ps1"
  - "**/*.psm1"
  - "**/*.psd1"
---

# PowerShell Rules

- Use `Set-StrictMode -Version Latest` where compatible.
- Use `try/catch` for error handling.
- Avoid `Write-Host` for functional output; use `Write-Output` or return values.
- Scripts MUST be idempotent (safe to run multiple times).
- Prefer Python over PowerShell when cross-platform compatibility is needed.
- Source of truth: `.github/instructions/development.instructions.md`
