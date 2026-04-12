# Documentation Standards

## Purpose

Normative requirements for documentation changes in this repository.

## Scope

Applies to:

- `README.md`
- `docs/**/*.md`
- Any runbook content under `docs/automation/runbooks/`

## Core Rules

### Single Source of Truth

REQUIRE:

- Maintain one authoritative location for each procedure.
- Prefer linking to the authoritative doc rather than duplicating text.

NEVER:

- Copy/paste step-by-step operational procedures into multiple documents.
- Create version-suffixed duplicates (`-v2`, `-new`, `-legacy`, `-archive`).

### Runbook Discipline

REQUIRE for `docs/automation/runbooks/**/*.md`:

- Procedures MUST be runnable as written.
- Steps MUST be ordered and unambiguous.
- Numbered headings MUST be sequential and consistent.

Validation:

- `pre-commit` enforces runbook heading numbering via `scripts/linting/validate_heading_numbers.py`.

### Linking

REQUIRE:

- Use relative links for repository content.
- Use stable links (prefer files that are part of SSOT, not transient artifacts).
- When referencing external standards (security, compliance, vendor docs), link to the authoritative source and avoid copying content into this repository.

NEVER:

- Link to local absolute paths (e.g., `C:\...`, `/opt/...`) in repo documentation.

### Change Scope

REQUIRE:

- Keep documentation diffs small and targeted.
- If a docs change depends on a code change, reference the code path and the intended behavior.

### Linting and Formatting

REQUIRE:

- Markdown changes MUST pass `pre-commit` hooks.
- Prefer fixing the underlying markdown issue over disabling lint rules.
- If a lint suppression is required, scope it narrowly and include justification.

## See Also

- [Markdown Style Guide](style-guides/markdown-style-guide.md)
- [Docker Compose YAML Style Guide](style-guides/docker-yaml-style-guide.md)
- [GitHub Platform Standards](github-platform-standards.md)
