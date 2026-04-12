"""Read the GitHub Actions event payload from ``GITHUB_EVENT_PATH``."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from scripts.common.json_utils import parse_json_object


def read_event_payload() -> dict[str, Any]:
    """Read the GitHub Actions event payload from ``GITHUB_EVENT_PATH``."""
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        return {}
    try:
        return parse_json_object(Path(event_path).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):  # TypeError: parse_json_object runtime check
        return {}
