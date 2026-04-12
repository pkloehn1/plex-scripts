"""Tests for scripts.common.json_utils."""

from __future__ import annotations

import pytest

from scripts.common.json_utils import parse_json_array, parse_json_object


class TestParseJsonObject:
    def test_valid_object(self) -> None:
        result = parse_json_object('{"key": "value"}')
        assert result == {"key": "value"}

    def test_nested_object(self) -> None:
        result = parse_json_object('{"a": {"b": 1}}')
        assert result == {"a": {"b": 1}}

    def test_empty_object(self) -> None:
        result = parse_json_object("{}")
        assert result == {}

    def test_bytes_input(self) -> None:
        result = parse_json_object(b'{"key": 1}')
        assert result == {"key": 1}

    def test_rejects_array(self) -> None:
        with pytest.raises(TypeError, match="Expected JSON object, got list"):
            parse_json_object("[1, 2, 3]")

    def test_rejects_scalar(self) -> None:
        with pytest.raises(TypeError, match="Expected JSON object, got int"):
            parse_json_object("42")

    def test_invalid_json_raises_json_error(self) -> None:
        with pytest.raises(Exception, match="Expecting"):
            parse_json_object("{bad json}")


class TestParseJsonArray:
    def test_valid_array(self) -> None:
        result = parse_json_array("[1, 2, 3]")
        assert result == [1, 2, 3]

    def test_array_of_objects(self) -> None:
        result = parse_json_array('[{"a": 1}, {"b": 2}]')
        assert result == [{"a": 1}, {"b": 2}]

    def test_empty_array(self) -> None:
        result = parse_json_array("[]")
        assert result == []

    def test_bytes_input(self) -> None:
        result = parse_json_array(b"[1, 2]")
        assert result == [1, 2]

    def test_rejects_object(self) -> None:
        with pytest.raises(TypeError, match="Expected JSON array, got dict"):
            parse_json_array('{"key": "value"}')

    def test_rejects_scalar(self) -> None:
        with pytest.raises(TypeError, match="Expected JSON array, got str"):
            parse_json_array('"hello"')

    def test_invalid_json_raises_json_error(self) -> None:
        with pytest.raises(Exception, match="Expecting"):
            parse_json_array("[bad json]")
