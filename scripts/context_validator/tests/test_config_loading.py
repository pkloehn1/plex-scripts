"""Tests for config loading functionality."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.common.paths import repo_root
from scripts.context_validator.config import load_config, parse_args


def test_load_config_returns_dict():
    """load_config should return a dictionary."""
    # Use the actual config file
    config_path = repo_root() / "scripts" / "copilot-context-health.conf"
    result = load_config(config_path)

    assert isinstance(result, dict)


def test_load_config_parses_required_keys():
    """load_config should parse all required keys from config."""
    config_path = repo_root() / "scripts" / "copilot-context-health.conf"
    result = load_config(config_path)

    # Verify required keys exist and are positive integers
    # Note: LLM provider limits are now in LLM_PROVIDERS dict, not config file
    required_keys = [
        "CHARS_PER_TOKEN",
        "INFO_THRESHOLD_PERCENT",
        "WARN_THRESHOLD_PERCENT",
    ]
    for key in required_keys:
        assert key in result, f"Missing required key: {key}"
        assert isinstance(result[key], int), f"{key} should be an integer"
        assert result[key] > 0, f"{key} should be positive"


def test_load_config_ignores_comments(tmp_path: Path):
    """load_config should ignore lines starting with #."""
    config_path = tmp_path / "test.conf"
    config_path.write_text("# This is a comment\nKEY=100\n  # Indented comment\n")

    result = load_config(config_path)
    assert result == {"KEY": 100}


def test_load_config_ignores_empty_lines(tmp_path: Path):
    """load_config should ignore empty lines."""
    config_path = tmp_path / "test.conf"
    config_path.write_text("KEY1=100\n\nKEY2=200\n")

    result = load_config(config_path)
    assert result == {"KEY1": 100, "KEY2": 200}


def test_load_config_missing_file_exits():
    """load_config should exit with error if file not found."""
    with pytest.raises(SystemExit):
        load_config(Path("/nonexistent/path/config.conf"))


def test_load_config_parses_float_values(tmp_path: Path):
    """load_config should parse values with decimal points as floats."""
    config_path = tmp_path / "test.conf"
    config_path.write_text("RATIO=3.14\n")

    result = load_config(config_path)
    assert result == {"RATIO": 3.14}
    assert isinstance(result["RATIO"], float)


def test_parse_args_defaults():
    """parse_args should return defaults with no arguments."""
    with patch.object(sys, "argv", ["script"]):
        args = parse_args()
    assert args.compare_to is None


def test_parse_args_compare_to():
    """parse_args should accept --compare-to flag."""
    with patch.object(sys, "argv", ["script", "--compare-to", "origin/main"]):
        args = parse_args()
    assert args.compare_to == "origin/main"
