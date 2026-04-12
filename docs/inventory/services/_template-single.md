# {Service Name}

<!-- template: single -->

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
| Image   |         |            |       |
| Port    |         |            |       |
| User    |         |            |       |

Stack: `{stack_name}` | Deploy: `make deploy-{stack}` | Smoke: `make smoke-test STACK={stack}`

## Storage

| Type | Location | Owner | Notes |
| ---- | -------- | ----- | ----- |
|      |          |       |       |

Type: `git` (this repo), `nfs` (NFS share), `local` (host filesystem).

## Access

| Interface | Scope | Method | URL / IP |
| --------- | ----- | ------ | -------- |
|           |       |        |          |

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

## Health check

| Method | Auth | Expected |
| ------ | ---- | -------- |
|        |      |          |

## Logs

| Destination | Access command | Format |
| ----------- | -------------- | ------ |
|             |                |        |

Destination: `docker` (stdout/stderr), `file` (container filesystem path).

## Secrets

| Name | Location | Owner |
| ---- | -------- | ----- |
|      |          |       |

## Pre-flight checks

- [ ] {Any prerequisites before deploying}

## Constraints

{Immutable requirements that cannot be changed.}

-

## Rollback

{How to back out this service.}
