---
applyTo: "**/docker-compose.yml,**/docker-compose.yaml,**/compose.yml,**/compose.yaml"
---

# Docker Compose Instructions

Path-specific instructions for Docker Compose YAML files.

## Core Rules

- Source of truth: `docs/repository-standards/style-guides/docker-yaml-style-guide.md`
- Swarm stacks live under `stacks/**/docker-compose.yml`.
- Use explicit document markers: start with `---`, end with `...`.
- Wrap YAML to 120 characters per line.

## Top-Level Key Order

REQUIRE this order: `include`, `services`, `networks`, `volumes`, `configs`, `secrets`.

NEVER include a top-level `name:` key in Swarm stack files.

## Service Key Order

REQUIRE keys in this category order: IDENTITY, LIFECYCLE, SECURITY, NETWORKING, RUNTIME, STORAGE, BEHAVIOR, RESOURCES, HEALTH, METADATA, EXTENSION.

See the style guide for the full key list per category.

## Invalid Swarm Keys

NEVER use these keys in Swarm stacks (not applied by `docker stack deploy`):

- `container_name`, `build`, `depends_on`, `restart`, `links`, `expose`
- `security_opt`, `userns_mode`, `cgroup_parent`, `network_mode`

Use `deploy.restart_policy` instead of `restart`. Use overlay networks instead of `links`.

## Image Tags

REQUIRE:

- No `:latest` tags.
- No digest/SHA pinning (`@sha256:...`).
- Prefer major version tags when published.

## Healthchecks

REQUIRE:

- CMD array format for all healthchecks (never CMD-SHELL).
- `timeout` must be less than `interval` with at least 10s gap.
- Select interval by service criticality (10s critical, 30s high, 60s standard, 120s low).

## Secrets

- Use Docker secrets for sensitive values (passwords, API tokens).
- Use environment variables only for non-sensitive configuration.
- Where supported, use the `*_FILE` environment variable pattern.

## Networking (Swarm)

- Do not use `ipv4_address` on overlay/external networks.
- Do not mount `/var/run/docker.sock` on application services (use a dedicated socket-proxy).

## Traefik Labels

REQUIRE this order within `labels:`: Provider Options, HTTP Routers, HTTP Services, HTTP Middlewares, TCP Routers, TCP Services, TCP Middlewares, UDP Routers, UDP Services.

Each label section requires a header comment identifying the section break.

## Linting

- `dclint` (Docker Compose-specific) and `yamllint` (general YAML) run via pre-commit.
- Use `docker compose config` for syntax validation before deployment.
