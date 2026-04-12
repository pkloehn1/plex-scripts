# Docker Compose YAML Style Guide - Research Summary

## Top-Level Compose File Keys

REQUIRE the following top-level keys in Docker Compose files, in this order:

| Order | Key        | Required  | Purpose                                      |
| ----- | ---------- | --------- | -------------------------------------------- |
| 1     | `name`     | Forbidden | Invalid in Swarm stacks (SWARM-SCHEMA-001)   |
| 2     | `include`  | No        | Import other compose files (Compose 2.20.3+) |
| 3     | `services` | Yes       | Service definitions                          |
| 4     | `networks` | No        | Custom network definitions                   |
| 5     | `volumes`  | No        | Named volume definitions                     |
| 6     | `configs`  | No        | Configuration objects                        |
| 7     | `secrets`  | No        | Secret definitions                           |

### Document markers and file placement

- New and modified Compose YAML MUST be a single document with explicit markers:
  start with `---` and end with `...`. Existing Compose files that lack end
  markers should be updated opportunistically; the `check-repo-layout` pre-commit
  hook enforces this for staged files.
- Swarm stacks live under `stacks/**/docker-compose.yml`.
- Do not place Compose files elsewhere; the `check-repo-layout` pre-commit hook
  enforces these invariants.

### Line Length (yamllint line-length)

REQUIRE:

- Wrap YAML to a maximum of 120 characters per line.
- Prefer reflowing labels, descriptions, and comments over disabling the rule.

ALLOW:

- Use a scoped `yamllint` disable for `line-length` when a value cannot be
  wrapped without breaking the configuration (for example, long URLs or Traefik
  labels).

Example (scoped exception):

```yaml
# yamllint disable rule:line-length
labels:
  - "traefik.http.routers.longrouter.rule=Host(`example.com`) && PathPrefix(`/some/really/long/path`)"
# yamllint enable rule:line-length
```

### Name Field Requirements

For Docker Swarm stack files (files deployed with `docker stack deploy`,
typically under `stacks/**/docker-compose.y*ml`):

- REQUIRE that top-level `name:` is NOT present.
- Rationale: Swarm stack naming is defined by the stack name argument to
  `docker stack deploy <stack>`. The Compose project name concept does not apply
  the same way and can conflict with Swarm tooling.

Swarm networking note:

- In Swarm stacks, do not use `ipv4_address` for services on overlay/external
  networks. Swarm assigns service and task addresses dynamically; static
  per-task IP assignment is ignored or misleading.
- If fixed addressing is required, use supported patterns instead:
  - Published ports with `mode: host` for direct host binding.
  - Swarm VIP / DNSRR for internal load-balanced endpoints.
  - Macvlan with the `--config-only` / `--config-from` pattern for Swarm-scope
    macvlan networks. Pre-create the network (see `scripts/edge/create_macvlan_networks.sh`)
    and reference it as `external: true` in the stack compose. Use `--ip-range x.x.x.x/32`
    to constrain IPAM to a single address per macvlan.

Swarm Docker socket note:

- In Swarm stacks, do not mount `/var/run/docker.sock` on application services.
- Exception: a dedicated `socket-proxy` service may mount the socket read-only to
  provide a restricted Docker API endpoint (e.g., `tcp://socket-proxy:2375`).
- Compensating controls: manager-only placement (if required by the API calls),
  internal overlay network, and a tight allowlist of permitted endpoints.

## Invalid Swarm Service Keys

The following service-level keys are **invalid** in Docker Swarm mode. They are
accepted syntactically by the Compose format but are **not applied** by
`docker stack deploy`, giving users a false expectation of functionality.

Stack definitions in this repo MUST NOT include any of these keys.

<!-- markdownlint-disable MD013 -->

| Key              | Check ID           | Why invalid                                                  | Alternative                                 |
| ---------------- | ------------------ | ------------------------------------------------------------ | ------------------------------------------- |
| `container_name` | SWARM-INVALID-001  | Not applied; Swarm auto-names replicas                       | Remove entirely                             |
| `build`          | SWARM-INVALID-002  | Not processed by `docker stack deploy`                       | Pre-build and push images to a registry     |
| `depends_on`     | SWARM-INVALID-003  | Not applied; Swarm manages service scheduling independently  | Remove entirely                             |
| `restart`        | SWARM-RESTART-001  | Not applied; use Swarm-native restart policy                 | Use `deploy.restart_policy`                 |
| `links`          | SWARM-INVALID-004  | Not applied; legacy Docker networking                        | Use overlay networks                        |
| `expose`         | SWARM-INVALID-005  | Not applied; services are auto-exposed on overlay networks   | Remove entirely                             |
| `security_opt`   | SWARM-SECURITY-001 | Not applied in Swarm mode                                    | Remove entirely                             |
| `userns_mode`    | SWARM-INVALID-006  | Not supported in Swarm mode                                  | Remove entirely                             |
| `cgroup_parent`  | SWARM-INVALID-007  | Not supported in Swarm mode                                  | Remove entirely                             |
| `network_mode`   | SWARM-NETWORK-001  | `network_mode: host` is not supported in Swarm mode          | Use overlay networks or `ports: mode: host` |

<!-- markdownlint-enable MD013 -->

The following keys **are valid** in Swarm mode (API v1.41+) and must not be
flagged: `cap_add`, `cap_drop`, `privileged`, `tmpfs`, `extra_hosts`, `sysctls`,
`devices` (via `deploy.resources`).

## Service Key Ordering

REQUIRE the following key order for Docker Compose service definitions.

`container_name` behavior:

- For Docker Swarm stacks (`docker stack deploy`), `container_name` is invalid
  and not applied. Swarm auto-names replicas using the stack and service names.
- Stack definitions in this repo MUST NOT include `container_name`
  (SWARM-INVALID-001).

<!-- markdownlint-disable MD013 -->

| Order | Category   | Keys (in presentation order)                                                                                                                                                                                                                                                                                                                                                               |
| ----- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1     | IDENTITY   | `container_name`, `image`, `build`, `hostname`, `domainname`, `platform`, `pull_policy`                                                                                                                                                                                                                                                                                                    |
| 2     | LIFECYCLE  | `restart`, `depends_on`, `profiles`, `init`, `scale`, `stop_signal`, `stop_grace_period`, `post_start`, `pre_stop`                                                                                                                                                                                                                                                                         |
| 3     | SECURITY   | `user`, `privileged`, `cap_add`, `cap_drop`, `security_opt`, `read_only`, `userns_mode`, `isolation`, `credential_spec`, `cgroup`, `cgroup_parent`                                                                                                                                                                                                                                         |
| 4     | NETWORKING | `network_mode`, `networks`, `ports`, `expose`, `extra_hosts`, `dns`, `dns_search`, `dns_opt`, `mac_address`, `links`, `external_links`                                                                                                                                                                                                                                                     |
| 5     | RUNTIME    | `secrets`, `environment`, `env_file`, `configs`                                                                                                                                                                                                                                                                                                                                            |
| 6     | STORAGE    | `volumes`, `volumes_from`, `tmpfs`, `shm_size`                                                                                                                                                                                                                                                                                                                                             |
| 7     | BEHAVIOR   | `entrypoint`, `command`, `working_dir`, `stdin_open`, `tty`, `attach`, `ipc`, `pid`, `uts`                                                                                                                                                                                                                                                                                                 |
| 8     | RESOURCES  | `deploy`, `logging`, `runtime`, `devices`, `device_cgroup_rules`, `gpus`, `group_add`, `blkio_config`, `cpu_count`, `cpu_percent`, `cpu_shares`, `cpu_period`, `cpu_quota`, `cpu_rt_runtime`, `cpu_rt_period`, `cpus`, `cpuset`, `mem_limit`, `mem_reservation`, `mem_swappiness`, `memswap_limit`, `oom_kill_disable`, `oom_score_adj`, `pids_limit`, `storage_opt`, `sysctls`, `ulimits` |
| 9     | HEALTH     | `healthcheck`                                                                                                                                                                                                                                                                                                                                                                              |
| 10    | METADATA   | `labels`, `annotations`                                                                                                                                                                                                                                                                                                                                                                    |
| 11    | EXTENSION  | `extends`, `develop`, `provider`, `use_api_socket`                                                                                                                                                                                                                                                                                                                                         |

<!-- markdownlint-enable MD013 -->

See the Swarm stack definitions under `stacks/` for reference implementations with section comments.

## Image Tag Policy

REQUIRE:

- No `:latest` tags.
- No digest/SHA pinning (e.g., `@sha256:...`).
- Prefer major version tags when the image publishes major-only tags.
- If a major-only tag is not published, pin to the next closest option the
  image supports (minor or patch).

### METADATA Category Details

#### Traefik Label Ordering

When using Traefik labels, REQUIRE the following order within the `labels:` key.

| Order | Group            | Pattern                                    |
| ----- | ---------------- | ------------------------------------------ |
| 1     | Provider Options | `traefik.enable`, `traefik.docker.network` |
| 2     | HTTP Routers     | `traefik.http.routers.<name>.*`            |
| 3     | HTTP Services    | `traefik.http.services.<name>.*`           |
| 4     | HTTP Middlewares | `traefik.http.middlewares.<name>.*`        |
| 5     | TCP Routers      | `traefik.tcp.routers.<name>.*`             |
| 6     | TCP Services     | `traefik.tcp.services.<name>.*`            |
| 7     | TCP Middlewares  | `traefik.tcp.middlewares.<name>.*`         |
| 8     | UDP Routers      | `traefik.udp.routers.<name>.*`             |
| 9     | UDP Services     | `traefik.udp.services.<name>.*`            |

Each section of the labels requires a header line to identify the section breaks
within the code.

## Sources Reviewed

- Docker official documentation (Compose file reference, include directive,
  Secrets, depends_on, Deploy specification, JSON-file logging, Networking)
- Community guides (SigNoz, Last9, Phase.dev, LinuxServer.io, Squadcast,
  Dash0)
- Single-operator discussions (Reddit r/selfhosted, r/Docker, TrueNAS forums,
  Dev Genius blog)
- Linting tools (docker-compose-linter/dclint, yamllint, compose_format)
- Stack Overflow patterns for healthchecks, depends_on, resource limits
- [OWASP Docker Top 10 (Docker Security)](https://owasp.org/www-project-docker-top-10/)

## External Security References

Use these as baseline hardening guidance for containerized services. This
repository does not copy their content; it links to the authoritative sources.

- [OWASP Docker Top 10 (Docker Security)](https://owasp.org/www-project-docker-top-10/)
  - Use when reviewing baseline hardening controls for container images and
    runtime configuration.
- [OWASP Docker Security (GitHub)](https://github.com/OWASP/Docker-Security)
  - Use when reviewing secrets handling and network segmentation guidance for
    Docker workloads.

## Healthcheck Findings

### Interval by Service Criticality

| Criticality | Services                              | Interval |
| ----------- | ------------------------------------- | -------- |
| Critical    | Reverse proxy, authentication, DNS    | 10s      |
| High        | Databases, message queues, cache      | 30s      |
| Standard    | Application services, APIs            | 60s      |
| Low         | Batch jobs, backup services, scrapers | 120s     |

Select the interval based on how quickly the service must recover from failure.
Critical services need faster detection.

### Start Period by Application Type

| Startup Speed | Application Types                                        | Start Period |
| ------------- | -------------------------------------------------------- | ------------ |
| Slow          | JVM-based applications (Jenkins), databases (PostgreSQL) | 60s - 120s   |
| Medium        | Python/Node.js apps, Redis, Nginx                        | 30s - 60s    |
| Fast          | Go binaries (Traefik), static file servers, Alpine       | 10s - 30s    |

Set `start_period` to match the application's typical startup time. Healthcheck
failures during `start_period` do not count toward the retry limit.

### Healthcheck Commands by Service Type

| Service Type  | Command                                                          |
| ------------- | ---------------------------------------------------------------- |
| HTTP API      | `["CMD", "curl", "-f", "http://localhost:PORT/health"]`          |
| PostgreSQL    | `["CMD", "pg_isready", "-U", "postgres"]`                        |
| Redis         | `["CMD", "redis-cli", "ping"]`                                   |
| Traefik       | `["CMD", "traefik", "healthcheck", "--ping"]`                    |
| MySQL/MariaDB | `["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"]` |
| MongoDB       | `["CMD", "mongosh", "--eval", "db.runCommand('ping').ok"]`       |
| RabbitMQ      | `["CMD", "rabbitmq-diagnostics", "check_running"]`               |
| Generic TCP   | `["CMD", "nc", "-z", "localhost", "PORT"]`                       |

Use the native healthcheck command provided by the application where available.
Replace PORT with the actual port number.

### Command Format

REQUIRE CMD array format for all healthchecks. NEVER use CMD-SHELL format.

### Timeout and Interval Relationship

`timeout` must be less than `interval` to prevent overlapping checks. REQUIRE
`interval - timeout >= 10s` as minimum gap before next check.

With `interval: 30s` and `timeout: 10s`, if a check starts at 0s and times out
at 10s, the next check starts at 30s, providing a 20s gap. If `timeout` equaled
or exceeded `interval`, a slow check could overlap with the next scheduled check.

## depends_on Findings

### Condition Types

| Condition                      | Use Case                             |
| ------------------------------ | ------------------------------------ |
| service_started                | Default; wait for container to start |
| service_healthy                | Wait for healthcheck to pass         |
| service_completed_successfully | Init containers that run and exit    |

Select the condition based on what the dependent service actually needs. REQUIRE
`service_healthy` for dependencies that need readiness (databases, caches).
NEVER use `service_started` for services with healthchecks defined.

The `restart` option re-triggers dependent container restart when dependency
restarts.

## Secrets Management Findings

### Secret Storage Methods

| Method                | Visibility          | Use Case                    |
| --------------------- | ------------------- | --------------------------- |
| Docker secrets        | Hidden from inspect | Passwords, API tokens       |
| Environment variables | Visible in inspect  | Non-sensitive configuration |

Select the method based on sensitivity. Use Docker secrets for any value that
would cause harm if exposed. Docker secrets mount to
`/run/secrets/SECRET_NAME` by default. Where supported, use the `*_FILE`
environment variable pattern to read secrets from files.

Swarm mode has native secrets management. Standalone Docker uses file-based
secrets with the `secrets:` top-level key.

## Include Directive Findings

Available in Compose 2.20.3+.

### Include vs Extends

| Feature  | include                        | extends            |
| -------- | ------------------------------ | ------------------ |
| Scope    | Entire compose file            | Single service     |
| Networks | Merged automatically           | Must be redeclared |
| Secrets  | Merged automatically           | Must be redeclared |
| Sources  | Local, OCI artifacts, Git URLs | Local files only   |

Select based on scope. Use `include` for reusable infrastructure components
(socket-proxy, logging sidecars). REQUIRE `include` for modular composition.
NEVER use `extends` for new implementations.

The `project_directory` option controls relative path resolution for included
files.

## File Organization Findings

### Single File vs Multiple Files

| Criteria                    | Single File | Multiple Files |
| --------------------------- | ----------- | -------------- |
| Full stack visibility       | Yes         | No             |
| Simpler deployment commands | Yes         | No             |
| Separation of concerns      | No          | Yes            |
| Independent lifecycles      | No          | Yes            |

### Coupling Indicators

| Indicator                  | Requires Single File |
| -------------------------- | -------------------- |
| depends_on relationship    | Yes                  |
| Shared internal network    | Yes                  |
| Log file dependencies      | Yes                  |
| External network (traefik) | No                   |

Use the coupling indicators to determine file organization. If any "Requires
Single File" indicator is present, keep services in the same compose file.

## Log Rotation Findings

REQUIRE log rotation for all production services. Without rotation, logs grow
unbounded and fill disk.

### Log Rotation Settings

| Setting  | Purpose                   | Value     |
| -------- | ------------------------- | --------- |
| driver   | Logging driver            | json-file |
| max-size | Maximum size per log file | 50m       |
| max-file | Number of rotated files   | 5         |

Configure log rotation per-service or globally in `daemon.json`.

## Resource Limits Findings

### Resource Limit Keys

| Key                            | Purpose            | Format         |
| ------------------------------ | ------------------ | -------------- |
| deploy.resources.limits.cpus   | Maximum CPU        | Decimal (0.5)  |
| deploy.resources.limits.memory | Maximum memory     | Suffix (512M)  |
| deploy.resources.reservations  | Guaranteed minimum | Same as limits |
| deploy.resources.limits.pids   | Process limit      | Integer        |

Memory accepts suffixes: `b`, `k`, `m`, `g`. Limits apply in both Compose and
Swarm modes.

Set limits based on observed usage plus headroom. Set reservations to guarantee
minimum resources for critical services.

## Linting Tools Findings

### Linting Tool Comparison

| Tool                  | Scope                   | Autofix |
| --------------------- | ----------------------- | ------- |
| dclint                | Docker Compose-specific | Yes     |
| Docker Compose config | Syntax and schema       | No      |
| yamllint              | General YAML            | No      |
| compose_format        | Formatting/ordering     | Yes     |

Use `docker compose config` for syntax validation before deployment. Use
`dclint` with autofix for consistent formatting across the repository.

## References

### Docker Official Documentation

- [Compose File Services Reference](https://docs.docker.com/reference/compose-file/services/)
- [Include Directive](https://docs.docker.com/compose/how-tos/multiple-compose-files/include/)
- [Secrets in Compose](https://docs.docker.com/compose/how-tos/use-secrets/)
- [depends_on and Startup Order](https://docs.docker.com/compose/how-tos/startup-order/)
- [Deploy Specification](https://docs.docker.com/reference/compose-file/deploy/)
- [JSON File Logging Driver](https://docs.docker.com/engine/logging/drivers/json-file/)
- [Networking in Compose](https://docs.docker.com/compose/how-tos/networking/)

### Community Guides

- [SigNoz - Docker Compose Healthcheck](https://signoz.io/guides/docker-compose-healthcheck/)
- [Last9 - Docker Healthcheck Guide](https://last9.io/blog/docker-healthcheck/)
- [Phase.dev - Docker Secrets Guide](https://phase.dev/blog/docker-secrets/)
- [LinuxServer.io - Networking Best Practices](https://docs.linuxserver.io/)
- [Squadcast - Docker Logging](https://www.squadcast.com/blog/docker-compose-logs)
- [Dash0 - Docker Logging Best Practices](https://www.dash0.com/blog/docker-logging-best-practices)

### Linting Tools

- [docker-compose-linter (dclint)](https://github.com/zavoloklom/docker-compose-linter)
- [yamllint](https://github.com/adrienverge/yamllint)
- [compose_format](https://github.com/funkyfuture/compose_format)

### Community Discussions (Unverified)

- [Reddit r/selfhosted](https://www.reddit.com/r/selfhosted/)
- [Reddit r/Docker](https://www.reddit.com/r/docker/)
- [TrueNAS Forums](https://www.truenas.com/community/forums/)
- [Dev Genius Blog](https://blog.devgenius.io/)
