"""Validation logic for context limits."""

from pathlib import Path
from typing import NamedTuple

from .utils import estimate_tokens, get_char_count, get_provider_for_file, get_provider_token_limit


class ValidationResult(NamedTuple):
    """Result of validating a single file."""

    path: str
    char_count: int
    token_count: int
    token_limit: int
    provider: str
    status: str  # "ok", "info", "warning", "error"


class CategoryResult(NamedTuple):
    """Result of validating a category budget."""

    category_name: str
    total_chars: int
    budget: int
    status: str  # "ok", "info", "warning", "error"


def validate_file(
    file_path: Path,
    chars_per_token: int,
    info_pct: int,
    warn_pct: int,
) -> ValidationResult:
    """Validate a single file against its provider-specific token limit.

    Args:
        file_path: Path to the file to validate.
        chars_per_token: Characters per token for estimation.
        info_pct: Percentage of limit for INFO status.
        warn_pct: Percentage of limit for WARN status.

    Returns:
        ValidationResult with provider-specific token limit applied.
    """
    char_count = get_char_count(file_path)
    token_count = estimate_tokens(char_count, chars_per_token)

    provider = get_provider_for_file(file_path)
    token_limit = get_provider_token_limit(provider)

    info_threshold = token_limit * info_pct // 100
    warn_threshold = token_limit * warn_pct // 100

    if token_count > token_limit:
        status = "error"
    elif token_count > warn_threshold:
        status = "warning"
    elif token_count > info_threshold:
        status = "info"
    else:
        status = "ok"

    return ValidationResult(
        path=str(file_path),
        char_count=char_count,
        token_count=token_count,
        token_limit=token_limit,
        provider=provider,
        status=status,
    )


def validate_category(
    category_name: str,
    total_chars: int,
    budget: int,
    info_threshold_percent: int,
    warn_threshold_percent: int,
) -> CategoryResult:
    """Validate a category's total character count against its budget.

    Args:
        category_name: Name of the category (e.g., "path_instructions").
        total_chars: Sum of all file character counts in this category.
        budget: Maximum allowed characters for this category.
        info_threshold_percent: Percentage of budget for INFO status.
        warn_threshold_percent: Percentage of budget for WARN status.

    Returns:
        CategoryResult with status: ok, info, warning, or error.
    """
    info_threshold = budget * info_threshold_percent // 100
    warn_threshold = budget * warn_threshold_percent // 100

    if total_chars > budget:
        status = "error"
    elif total_chars > warn_threshold:
        status = "warning"
    elif total_chars > info_threshold:
        status = "info"
    else:
        status = "ok"

    return CategoryResult(
        category_name=category_name,
        total_chars=total_chars,
        budget=budget,
        status=status,
    )
