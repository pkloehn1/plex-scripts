---
applyTo: "**"
---

# Data & State Management

Instructions for configuration hierarchy, secret handling, persistence, and backup/restore expectations.

## Configuration hierarchy

- Treat configuration as code: keep static service configuration in `app-config/` and stack definitions in `stacks/`.
- Keep a strict separation between:
  - Repo content (tracked)
  - Runtime state (service data volumes)
  - Logs
- Do not hardcode environment-specific values in files when an environment variable or secret is the intended mechanism.

## Secrets

- Never commit secret material (tokens, passwords, private keys).
- Prefer Docker secrets over plain environment variables for credentials.
- If a service supports it, prefer the `*_FILE` environment variable pattern wired to Docker secrets.
- Keep secret _values_ out of the repo; if the repo contains placeholder secret filenames, do not replace them with real values.

## Persistence

- For any stateful service, define explicit persistent storage (named volumes or bind mounts) and document what data is persisted.
- Avoid mixing application binaries/config with runtime data in the same mount.

## Backup and restore

- Treat backups as part of "done" for stateful changes.
- Prefer service-appropriate backups (database dumps/snapshots) over ad-hoc filesystem copies.
- Periodically validate restores for critical services.

## Deployment path standards

Keep paths consistent across nodes when deploying services.

Minimum layout:

- `/home/alvis-andrews/repos/docker-swarm-homelab` — Repository root (cloned on each node). Git tracked: Yes
- `/home/alvis-andrews/repos/docker-swarm-homelab/app-config/{service}` — Static configuration per service. Git tracked: Yes
- `/home/alvis-andrews/repos/docker-swarm-homelab/secrets` — Secret files (used with Docker secrets where applicable). Git tracked: No
- `/opt/services/data/{service}` — Local transactional data (default). Git tracked: No
- `/opt/services/app-data/{service}` — Durable state (may be NFS-backed). Git tracked: No
- `/opt/services/logs/{service}` — Service log files (always local). Git tracked: No

Windows repo root (laptop):

- `C:/Users/petek/repos/docker-swarm-homelab`
