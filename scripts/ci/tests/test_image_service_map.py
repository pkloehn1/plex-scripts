"""Tests for the image-to-service-label mapping and normalization logic."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from scripts.ci.image_service_map import (
    EXCLUDED_IMAGES,
    is_compose_file,
    load_map,
    normalize_image_name,
)
from scripts.ci.merge_label_files import merge_label_files
from scripts.common.paths import repo_root

_REPO_ROOT = repo_root()
_GITHUB_DIR = _REPO_ROOT / ".github"
_STACKS_DIR = _REPO_ROOT / "stacks"
_IMAGE_RE = re.compile(r"^\s*image:\s*['\"]?([^\s'\"#]+)", re.MULTILINE)


# ---------------------------------------------------------------------------
# Mapping file validation
# ---------------------------------------------------------------------------


def test_map_loads_and_is_valid_json() -> None:
    mapping = load_map()
    assert isinstance(mapping, dict)
    assert mapping, "Mapping must be non-empty"
    for key, value in mapping.items():
        assert isinstance(key, str) and key, f"Invalid key: {key!r}"
        assert isinstance(value, str) and value, f"Invalid value for {key!r}: {value!r}"


def test_all_labels_exist_in_labels_yml(tmp_path: Path) -> None:
    mapping = load_map()
    merged_path = tmp_path / "labels-merged.yml"
    merge_label_files(_GITHUB_DIR / "labels-hub.yml", _GITHUB_DIR / "labels-spoke.yml", merged_path)
    labels_raw = yaml.safe_load(merged_path.read_text(encoding="utf-8"))
    assert isinstance(labels_raw, list)
    known_labels = {entry["name"] for entry in labels_raw if isinstance(entry, dict) and "name" in entry}

    for image, label in mapping.items():
        assert label in known_labels, (
            f"Mapping value {label!r} (for image {image!r}) does not exist in labels-hub.yml + labels-spoke.yml"
        )


def test_all_labels_are_service_labels() -> None:
    mapping = load_map()
    for image, label in mapping.items():
        assert label.startswith("service/"), f"Label {label!r} for image {image!r} is not a service/* label"


def test_no_duplicate_labels() -> None:
    mapping = load_map()
    seen: dict[str, str] = {}
    for image, label in mapping.items():
        if label in seen:
            pytest.fail(f"Duplicate label {label!r}: mapped by both {seen[label]!r} and {image!r}")
        seen[label] = image


# ---------------------------------------------------------------------------
# Image name normalization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("traefik:v3.6", "traefik"),
        ("crowdsecurity/crowdsec:v1.7.6", "crowdsecurity/crowdsec"),
        ("ghcr.io/goauthentik/server:2025.12.1", "goauthentik/server"),
        ("docker.io/library/postgres:18.1-alpine", "postgres"),
        ("portainer/portainer-ee:2.33.6", "portainer/portainer-ee"),
        ("louislam/uptime-kuma:2", "louislam/uptime-kuma"),
        ("wollomatic/socket-proxy:1", "wollomatic/socket-proxy"),
        ("favonia/cloudflare-ddns:1", "favonia/cloudflare-ddns"),
        ("ghcr.io/corazawaf/coraza-spoa:0.5.0", "corazawaf/coraza-spoa"),
        # Edge cases
        ("nginx", "nginx"),
        ("nginx:latest", "nginx"),
        ("registry.example.com:5000/myapp:v2", "myapp"),
        ("docker.io/library/redis:7", "redis"),
    ],
)
def test_normalize_image_name(raw: str, expected: str) -> None:
    assert normalize_image_name(raw) == expected


# ---------------------------------------------------------------------------
# Compose file detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("stacks/edge/docker-compose.yml", True),
        ("stacks/control/docker-compose.yml", True),
        ("stacks/media/compose.yml", True),
        ("stacks/edge/docker-compose.override.yml", True),
        ("scripts/ci/image_service_map.py", False),
        (".github/workflows/auto-labeler.yml", False),
        ("README.md", False),
    ],
)
def test_is_compose_file(path: str, expected: bool) -> None:
    assert is_compose_file(path) is expected


# ---------------------------------------------------------------------------
# Coverage: deployed images have mapping entries
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _STACKS_DIR.is_dir(), reason="stacks/ not present in this repo")
def test_deployed_images_covered() -> None:
    """Every image in stacks/ Compose files has a mapping entry or is excluded."""
    mapping = load_map()
    compose_files = list(_STACKS_DIR.rglob("docker-compose*.yml")) + list(_STACKS_DIR.rglob("compose*.yml"))
    assert compose_files, "No Compose files found in stacks/"

    missing: list[str] = []
    for compose_path in compose_files:
        content = compose_path.read_text(encoding="utf-8")
        for match in _IMAGE_RE.finditer(content):
            raw_image = match.group(1)
            normalized = normalize_image_name(raw_image)
            if normalized not in mapping and normalized not in EXCLUDED_IMAGES:
                missing.append(f"{compose_path.relative_to(_REPO_ROOT)}: {raw_image} -> {normalized}")

    assert not missing, "Deployed images missing from mapping and not in EXCLUDED_IMAGES:\n" + "\n".join(
        f"  - {entry}" for entry in missing
    )
