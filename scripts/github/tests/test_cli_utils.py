"""Tests for cli_utils module."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pytest

from scripts.github.cli_utils import (
    casefold_nonempty_str,
    normalize_nonempty_str,
    read_optional_text,
    read_required_text,
    resolve_body,
)

# -- normalize_nonempty_str ----------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("hello", "hello"),
        ("  spaced  ", "spaced"),
        ("", None),
        ("   ", None),
        (None, None),
        (42, None),
        ([], None),
    ],
)
def test_normalize_nonempty_str(value: Any, expected: str | None) -> None:
    assert normalize_nonempty_str(value) == expected


# -- casefold_nonempty_str -----------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Hello", "hello"),
        ("  WORLD  ", "world"),
        ("", None),
        (None, None),
        (42, None),
    ],
)
def test_casefold_nonempty_str(value: Any, expected: str | None) -> None:
    assert casefold_nonempty_str(value) == expected


# -- read_optional_text --------------------------------------------------------


def test_read_optional_text_none_both() -> None:
    assert read_optional_text(text=None, path=None) is None


def test_read_optional_text_direct_string() -> None:
    assert read_optional_text(text="body text", path=None) == "body text"


def test_read_optional_text_from_file(tmp_path: Path) -> None:
    body_file = tmp_path / "body.md"
    body_file.write_text("file body", encoding="utf-8")
    assert read_optional_text(text=None, path=body_file) == "file body"


def test_read_optional_text_raises_on_both(tmp_path: Path) -> None:
    body_file = tmp_path / "body.md"
    body_file.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="only one"):
        read_optional_text(text="inline", path=body_file)


# -- read_required_text --------------------------------------------------------


def test_read_required_text_returns_text() -> None:
    assert read_required_text(text="content", path=None) == "content"


def test_read_required_text_raises_on_none() -> None:
    with pytest.raises(ValueError, match="Body is required"):
        read_required_text(text=None, path=None)


def test_read_required_text_raises_on_whitespace_only() -> None:
    with pytest.raises(ValueError, match="Body is required"):
        read_required_text(text="   ", path=None)


# -- resolve_body --------------------------------------------------------------


def test_resolve_body_returns_none_when_both_args_are_none() -> None:
    namespace = argparse.Namespace(body=None, body_file=None)
    assert resolve_body(namespace) is None
