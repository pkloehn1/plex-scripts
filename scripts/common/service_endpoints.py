"""Service endpoint mappings for the homelab Traefik-routed services."""

from __future__ import annotations

# Recyclarr instance name (recyclarr.yml key) -> Traefik base URL or FQDN
SERVARR_FQDNS: dict[str, str] = {
    "sonarr": "tv.kloehnwars.com",
    "radarr": "movies.kloehnwars.com",
    "radarr-se": "api.kloehnwars.com/radarr-se",
    "radarr-4k": "movies-4k.kloehnwars.com",
    "radarr-4k-se": "api.kloehnwars.com/radarr-4k-se",
    "radarr-concerts": "concerts.kloehnwars.com",
}
