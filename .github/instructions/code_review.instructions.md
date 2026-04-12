---
applyTo: "**"
excludeAgent: ["coding-agent"]
---

# Copilot Code Review Instructions

These instructions apply to Copilot code review only.

## Review quality bar

- Prefer high-signal comments: correctness, security, data-loss risk, CI breakage, and maintainability.
- Verify claims before commenting:
  - If reporting a missing file, check whether it is ignored (for example via `.gitignore`) versus truly absent.
  - If reporting a broken reference, confirm the referenced path exists in the repository tree for the PR head.
- When suggesting changes, prefer the smallest fix that satisfies the intent and matches existing repo conventions.

## Repo-specific expectations

- Do not request `git push`.
- Avoid recommendations that would commit secrets or add hardcoded credentials.
- For infrastructure changes, ensure paths and persistence conventions match existing repo docs.

## Where to look (source of truth)

- Repo-wide guidance: [.github/copilot-instructions.md](../../.github/copilot-instructions.md)
- Path-scoped Copilot instructions: [.github/instructions/](../../.github/instructions/)
- Swarm conventions: [docs/repository-standards/style-guides/docker-yaml-style-guide.md](../../docs/repository-standards/style-guides/docker-yaml-style-guide.md)
- Documentation standards: [docs/repository-standards/documentation-standards.md](../../docs/repository-standards/documentation-standards.md)
- Markdown style: [docs/repository-standards/style-guides/markdown-style-guide.md](../../docs/repository-standards/style-guides/markdown-style-guide.md)
- Python style: [docs/repository-standards/style-guides/python-style-guide.md](../../docs/repository-standards/style-guides/python-style-guide.md)
- Shell style: [docs/repository-standards/style-guides/shell-style-guide.md](../../docs/repository-standards/style-guides/shell-style-guide.md)

## Review focus by technology

### Docker Swarm

- Reject `:latest` image tags; require pinned tags consistent with repo conventions.
- Require secrets to use Docker secrets (and `*_FILE` patterns when supported) rather than plaintext env vars.
- Verify volume mounts:
  - Static config belongs in `app-config/{service}`.
  - Runtime data/logs belong in the documented Swarm paths and should not be mixed with config.
- In Swarm stacks, ensure any node-local paths are absolute (Swarm portability assumption).
- Ensure service definitions follow the repo's compose key ordering and conventions.

### Python

- Dependencies should be managed via `pyproject.toml` (avoid introducing/expanding `requirements.txt`).
- Require TDD for non-trivial logic and keep repo-wide coverage at 100%.

### Shell / PowerShell

- Scripts MUST be idempotent and safe-by-default.
- Avoid adding destructive operations without clear guardrails.

### CI/CD and GitHub Actions

- Follow the repo's CI/CD instruction file: [.github/instructions/cicd.instructions.md](../../.github/instructions/cicd.instructions.md).
- Ensure workflows respect the repo's rules around reusable workflows/composite actions and minimal permissions.

### Security and secrets

- Enforce "no secrets in git" (tokens, passwords, keys).

## Review findings format

Present all findings in a unified table with a sequential `Finding` column for cross-referencing with options tables.

| Finding | Source      | Severity | Category    | File:Line    | Description          |
|---------|-------------|----------|-------------|--------------|----------------------|
| 1       | Copilot     | WARNING  | Convention  | config.py:42 | Missing type hint    |
| 2       | SonarCloud  | ERROR    | Security    | auth.py:15   | Hardcoded credential |
| 3       | Self        | WARNING  | Propagation | README.md:15 | Stale helper example |

Severity levels:

| Severity | Meaning                            | Action     |
| -------- | ---------------------------------- | ---------- |
| ERROR    | Bug, security flaw, or CI breakage | Must fix   |
| WARNING  | Convention violation or gap        | Should fix |
| INFO     | Suggestion or minor improvement    | Consider   |

For ERROR and WARNING findings, include an options table referencing the finding number:

| Finding | Approach | Resilience | Description |
|---------|----------|------------|-------------|
| 1A      | ...      | Short-term | ...         |
| 1B      | ...      | Long-term  | ...         |
