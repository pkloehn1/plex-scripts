"""Utilities for the image-to-service-label mapping used by the auto-labeler."""

from __future__ import annotations

import json
import re
from pathlib import Path

from scripts.common.paths import repo_root

# Keys are normalized image names (no registry prefix, no tag).
# See normalize_image_name() below for the stripping logic.
_MAP_PATH = repo_root() / ".github" / "image-service-map.json"

# Images intentionally excluded from the mapping (ambiguous: one image serves
# multiple service labels depending on context).
EXCLUDED_IMAGES: frozenset[str] = frozenset(
    {
        "postgres",
        "goauthentik/server",
        "portainer/agent",
        "tiredofit/traefik-cloudflare-companion",
    }
)

_COMPOSE_FILENAME_RE = re.compile(
    r"(?:^|/)(?:docker-)?compose(?:\.[^/]+)?\.ya?ml$",
    re.IGNORECASE,
)


def load_map(path: Path | None = None) -> dict[str, str]:
    """Load the image-service-map JSON and return it as a dict."""
    target = path or _MAP_PATH
    result: dict[str, str] = json.loads(target.read_text(encoding="utf-8"))
    return result


def normalize_image_name(raw: str) -> str:
    """Normalize a Docker image reference to its canonical base name.

    Strips the tag, registry prefix, and ``library/`` prefix so that
    image references like ``ghcr.io/org/image:v1.2.3`` become ``org/image``
    and ``docker.io/library/postgres:16`` becomes ``postgres``.
    """
    name = re.sub(r":[\w][\w.-]*$", "", raw)

    parts = name.split("/")
    if len(parts) >= 2 and ("." in parts[0] or ":" in parts[0]):
        parts = parts[1:]
        name = "/".join(parts)

    if name.startswith("library/"):
        name = name[len("library/") :]

    return name


def is_compose_file(path: str) -> bool:
    """Return True if *path* looks like a Docker Compose YAML filename."""
    return bool(_COMPOSE_FILENAME_RE.search(path))
