---
paths:
  - "**/docker-compose.yml"
  - "**/docker-compose.yaml"
  - "**/compose.yml"
  - "**/compose.yaml"
---

# Docker Compose Rules

- Swarm stacks live under `stacks/**/docker-compose.yml`.
- Use explicit document markers: start with `---`, end with `...`.
- Wrap YAML to 120 characters per line.
- Top-level key order: `include`, `services`, `networks`, `volumes`, `configs`, `secrets`.
- Never include top-level `name:` in Swarm stack files.
- Service key order: IDENTITY, LIFECYCLE, SECURITY, NETWORKING, RUNTIME, STORAGE, BEHAVIOR, RESOURCES, HEALTH, METADATA, EXTENSION.
- No `:latest` tags. No digest/SHA pinning. Prefer major version tags.
- CMD array format for healthchecks (never CMD-SHELL).
- Source of truth: `docs/repository-standards/style-guides/docker-yaml-style-guide.md`
