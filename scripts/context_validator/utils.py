"""Utility functions for context validation."""

import fnmatch
from pathlib import Path

from .config import LLM_PROVIDERS


def get_provider_for_file(file_path: Path) -> str:
    """Detect LLM provider from filename pattern.

    Args:
        file_path: Path to the instruction file.

    Returns:
        Provider key (e.g., 'anthropic', 'google', 'default').
    """
    filename = file_path.name
    rel_path = str(file_path).replace("\\", "/")

    for provider_key, config in LLM_PROVIDERS.items():
        if provider_key == "default":
            continue  # Check default last
        for pattern in config["file_patterns"]:
            if fnmatch.fnmatch(filename, pattern) or fnmatch.fnmatch(rel_path, pattern):
                return provider_key

    return "default"


def get_provider_token_limit(provider_key: str) -> int:
    """Get instruction token limit for a provider.

    Args:
        provider_key: Provider key (e.g., 'anthropic', 'google').

    Returns:
        Token limit for instruction files (4% of context window).
    """
    config = LLM_PROVIDERS.get(provider_key, LLM_PROVIDERS["default"])
    context_tokens = config["context_window_tokens"]
    limit_pct = config["instruction_limit_pct"]
    limit: int = context_tokens * limit_pct // 100
    return limit


def get_char_count(file_path: Path) -> int:
    """Get character count of a file."""
    try:
        with open(file_path, encoding="utf-8") as f:
            return len(f.read())
    except (OSError, UnicodeDecodeError):
        return 0


def estimate_tokens(char_count: int, chars_per_token: int = 4) -> int:
    """Estimate token count from character count.

    Args:
        char_count: Number of characters.
        chars_per_token: Average characters per token (default: 4 for English/code).

    Returns:
        Estimated number of tokens, rounded up.
    """
    if char_count == 0:
        return 0
    # Use ceiling division to round up
    return (char_count + chars_per_token - 1) // chars_per_token


def find_files(root: Path, pattern: str) -> list[Path]:
    """Find files matching a glob pattern or exact path."""
    # Check if it's an exact file path first
    exact_path = root / pattern
    if exact_path.is_file():
        return [exact_path]
    # Otherwise use glob
    return list(root.glob(pattern))
