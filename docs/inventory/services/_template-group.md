# {Service Group Name}

<!-- template: group -->

{One-line description.}

## Sources

| Link     | URL |
| -------- | --- |
| Registry |     |
| Repo     |     |
| Docs     |     |

## Configuration

| Setting | Default | Configured | Notes |
| ------- | ------- | ---------- | ----- |
|         |         |            |       |

## Swarm services

| Component | Image | Port | User | Resources (limit / reserve) |
| --------- | ----- | ---- | ---- | --------------------------- |
|           |       |      |      |                             |

Stack: `{stack_name}` | Deploy: `make deploy-{stack}` | Smoke: `make smoke-test STACK={stack}`

## Storage

| Component | Type | Location | Owner | Notes |
| --------- | ---- | -------- | ----- | ----- |
|           |      |          |       |       |

Type: `git` (this repo), `nfs` (NFS share), `local` (host filesystem).

## Dependency order

1. {First service to start — typically data stores}
2. {Services that depend on #1}
3. {Services that depend on #2}

## Access

| Component | Interface | Scope | Method | URL / IP |
| --------- | --------- | ----- | ------ | -------- |
|           |           |       |        |          |

Scope: `external` (internet via reverse proxy), `internal` (LAN direct or internal route), `overlay` (Docker overlay only), `outbound` (initiates connections, no inbound).

## Routing

| Subdomain | Router type | Target | Priority | Middleware |
| --------- | ----------- | ------ | -------- | ---------- |
|           |             |        |          |            |

## Auth

| Layer           | Method | Details |
| --------------- | ------ | ------- |
| Service admin   |        |         |
| SSO             |        |         |
| API consumers   |        |         |

## Health checks

| Component | Method | Auth | Expected |
| --------- | ------ | ---- | -------- |
|           |        |      |          |

## Logs

| Component | Destination | Access command | Format |
| --------- | ----------- | -------------- | ------ |
|           |             |                |        |

Destination: `docker` (stdout/stderr), `file` (container filesystem path).

## Secrets

| Name | Location | Owner | Used by |
| ---- | -------- | ----- | ------- |
|      |          |       |         |

## Pre-flight checks

- [ ] {Directories created with correct ownership}
- [ ] {Secrets files created}
- [ ] {Sysctl or host-level requirements met}
- [ ] {DNS records in place}
- [ ] {Dependent services healthy}

## Constraints

{Immutable requirements that cannot be changed.}

-

## Rollback

{How to back out this service group. Note dependency order for teardown.}
