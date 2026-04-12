from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.inventory.generate_nodes_report_jsonc import (
    _consume_block_comment,
    _consume_line_comment,
    _consume_string,
    _load_nodes_records,
    strip_jsonc_comments,
)

# ── _consume_string ───────────────────────────────────────────────────────────


def test_consume_string_escape_sequence() -> None:
    text = r'"hello\"world"'
    segment, pos = _consume_string(text, 0)
    assert segment == text
    assert pos == len(text)


def test_consume_string_unterminated_returns_all() -> None:
    text = '"unterminated'
    segment, pos = _consume_string(text, 0)
    assert segment == text
    assert pos == len(text)


def test_consume_string_closed_normally() -> None:
    text = '"hello" rest'
    segment, pos = _consume_string(text, 0)
    assert segment == '"hello"'
    assert pos == 7


# ── _consume_line_comment ─────────────────────────────────────────────────────


def test_consume_line_comment_stops_at_newline() -> None:
    text = "// this is a comment\ncode"
    pos = _consume_line_comment(text, 0)
    assert text[pos] == "\n"


def test_consume_line_comment_reaches_end() -> None:
    text = "// no newline"
    pos = _consume_line_comment(text, 0)
    assert pos == len(text)


# ── _consume_block_comment ────────────────────────────────────────────────────


def test_consume_block_comment_terminated() -> None:
    text = "/* block */ rest"
    pos = _consume_block_comment(text, 0)
    assert text[pos:] == " rest"


def test_consume_block_comment_unterminated_returns_len() -> None:
    text = "/* never closed"
    pos = _consume_block_comment(text, 0)
    assert pos == len(text)


# ── strip_jsonc_comments ─────────────────────────────────────────────────────


def test_strip_jsonc_comments_block_comment() -> None:
    text = '{"a": /* remove this */ 1}'
    result = strip_jsonc_comments(text)
    parsed = json.loads(result)
    assert parsed["a"] == 1


def test_strip_jsonc_comments_string_preserves_slashes() -> None:
    text = '{"url": "http://example.com"}'
    result = strip_jsonc_comments(text)
    assert "http://example.com" in result


# ── _load_nodes_records ───────────────────────────────────────────────────────


def test_load_nodes_records_raises_when_not_mapping(tmp_path: Path) -> None:
    yml = tmp_path / "nodes.yml"
    yml.write_text("- just a list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a mapping"):
        _load_nodes_records(yml)


def test_load_nodes_records_raises_when_nodes_not_list(tmp_path: Path) -> None:
    yml = tmp_path / "nodes.yml"
    yml.write_text("version: 1\nnodes: not-a-list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="'nodes' list"):
        _load_nodes_records(yml)
