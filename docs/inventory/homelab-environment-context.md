# Homelab Environment Context

Cross-repo reference for AI agents and developers working in any spoke repository. This document is synced from `repo-template` to all spoke repos via hub-and-spoke sync.

## Repositories

| Repository | Role | Primary Content |
| --- | --- | --- |
| `kloehnwars-homelab` | IaC and node provisioning | Terraform, Ansible, control-node automation |
| `docker-swarm-homelab` | Container platform | Docker Swarm stacks, service deployment, app-config |
| `docker-compose-homelab` | Standalone containers | Docker Compose for non-Swarm services |
| `repo-template` | Standards hub | AI directives, linter configs, shared scripts, sync engine |

## Node Roles

The homelab runs Docker Swarm on bare-metal Ubuntu nodes. Each node has one role:

- **Manager**: participates in Raft consensus, schedules services, runs control-plane stacks.
- **Worker**: runs application stacks, does not participate in consensus.
- **Edge**: worker with dual-homed networking (DMZ + LAN macvlan) for ingress.

Node inventory and hostnames are maintained in `docker-swarm-homelab/docs/inventory/nodes.md`.

## Network Zones

| VLAN | CIDR | Purpose |
| --- | --- | --- |
| 20 (DMZ) | 192.168.20.0/24 | External entrypoints. Traefik DMZ VIP at 192.168.20.200. |
| 40 (LAN) | 10.10.40.0/24 | Internal services and Swarm nodes. Traefik LAN VIP at 10.10.40.200. |

## Domain and DNS

- **External domain**: kloehnwars.com (Cloudflare DNS + proxy).
- **Split-horizon**: Unifi resolves internal queries to the LAN VIP; external queries route through Cloudflare to the DMZ VIP (see table above).
- **Ingress VIPs**: Traefik is dual-homed via macvlan networks on the edge node.

## Active Services

Deployed and running in `docker-swarm-homelab`:

### Identity and access

- **Authentik**: SSO/OIDC identity provider with forward-auth middleware on Traefik.
- **FreeIPA**: Planned as LDAP backend for Authentik. Not on critical path for MVP.

### Ingress and security

- **Traefik v3**: Reverse proxy with file-based and Swarm-label routing. Dual-homed (DMZ + LAN macvlan).
- **CrowdSec**: Threat intelligence with Traefik bouncer plugin.

### API management

- **Gravitee APIM CE**: API gateway for servarr services with analytics dashboard.

### Media automation

- **Servarr stack**: Sonarr, Radarr (5 variants), Prowlarr, Lidarr, Bazarr, Bookshelf, Seerr.
- **Recyclarr**: Scheduled configuration sync for media services (6-hour cadence).
- **SABnzbd**: Usenet download client (TrueNAS macvlan, not Swarm).

### Monitoring and observability

- **Prometheus**: Metrics collection.
- **Grafana**: Dashboards.
- **Loki**: Log aggregation.
- **Uptime Kuma**: Service health checks.
- **Node Exporter**: Per-node system metrics.

### Management

- **Portainer**: Docker Swarm cluster UI.

### Data stores (on TrueNAS)

- **PostgreSQL**: Authentik and Servarr databases.
- **MongoDB**: Gravitee APIM data.
- **Elasticsearch**: Gravitee analytics.

### Utilities

- **Dozzle**: Real-time Docker log viewer.
- **Cloudflare Companion**: Automatic CNAME creation.

## Planned Services

- **GitLab CE**: Source control and CI/CD (control node).
- **Wazuh**: SIEM and IDS/IPS.
- **VPN Gateway**: Remote access.
- **LLM stack**: Local AI inference.
- **AMP game servers**: CubeCoders game server platform (Windows worker node).

## Consul

Deferred. Docker Swarm provides native service discovery. Consul may be re-added if cross-service configuration or multi-datacenter value emerges.

## Filesystem Paths

### Linux nodes

| Path | Purpose |
| --- | --- |
| `/home/alvis-andrews/repos/<repo>` | Git repository clones |
| `/opt/services/app-data/<service>` | Runtime data (not git-tracked) |
| `/opt/services/logs` | Centralized service logs |
| `/mnt/media` | NFS media library (TrueNAS) |
| `/mnt/downloads` | NFS download staging (TrueNAS) |

### Windows workstation

| Path | Purpose |
| --- | --- |
| `C:\Users\petek\repos\<repo>` | Git repository clones |
