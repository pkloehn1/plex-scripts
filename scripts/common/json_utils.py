"""Typed wrappers around :func:`json.loads` for mypy-safe JSON parsing."""

from __future__ import annotations

import json
from typing import Any


def parse_json_object(text: str | bytes) -> dict[str, Any]:
    """Parse JSON text that is expected to contain an object (``{...}``).

    Raises :class:`TypeError` when the parsed value is not a dict.
    """
    result = json.loads(text)
    if not isinstance(result, dict):
        raise TypeError(f"Expected JSON object, got {type(result).__name__}")
    return result


def parse_json_array(text: str | bytes) -> list[Any]:
    """Parse JSON text that is expected to contain an array (``[...]``).

    Raises :class:`TypeError` when the parsed value is not a list.
    """
    result = json.loads(text)
    if not isinstance(result, list):
        raise TypeError(f"Expected JSON array, got {type(result).__name__}")
    return result
