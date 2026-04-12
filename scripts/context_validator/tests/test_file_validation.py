"""Tests for file validation functionality."""

from pathlib import Path

from scripts.context_validator.stats import compute_baseline_stats, detect_outliers
from scripts.context_validator.utils import (
    estimate_tokens,
    get_char_count,
    get_provider_for_file,
    get_provider_token_limit,
)
from scripts.context_validator.validator import validate_category, validate_file


def test_validate_file_ok(tmp_path: Path):
    """validate_file should return ok status for file under info threshold."""
    # With 4 chars/token and 8000 token limit (default provider), 1000 chars = 250 tokens
    # 250 tokens is ~3% of 8000, well under 50% info threshold
    file_path = tmp_path / "small.md"
    file_path.write_text("a" * 1000)

    result = validate_file(file_path, chars_per_token=4, info_pct=50, warn_pct=75)

    assert result.status == "ok"
    assert result.char_count == 1000
    assert result.token_count == 250
    assert result.provider == "default"


def test_validate_file_info(tmp_path: Path):
    """validate_file should return info status for file above info threshold."""
    # Need > 50% of 8000 tokens = 4000 tokens = 16000 chars
    file_path = tmp_path / "medium.md"
    file_path.write_text("a" * 20000)  # 5000 tokens, ~62.5% of 8000

    result = validate_file(file_path, chars_per_token=4, info_pct=50, warn_pct=75)

    assert result.status == "info"
    assert result.char_count == 20000
    assert result.token_count == 5000


def test_validate_file_warning(tmp_path: Path):
    """validate_file should return warning status for file above warn threshold."""
    # Need > 75% of 8000 tokens = 6000 tokens = 24000 chars
    file_path = tmp_path / "large.md"
    file_path.write_text("a" * 28000)  # 7000 tokens, 87.5% of 8000

    result = validate_file(file_path, chars_per_token=4, info_pct=50, warn_pct=75)

    assert result.status == "warning"
    assert result.char_count == 28000
    assert result.token_count == 7000


def test_validate_file_error(tmp_path: Path):
    """validate_file should return error status for file over limit."""
    # Need > 8000 tokens = 32000 chars
    file_path = tmp_path / "huge.md"
    file_path.write_text("a" * 36000)  # 9000 tokens, over 8000 limit

    result = validate_file(file_path, chars_per_token=4, info_pct=50, warn_pct=75)

    assert result.status == "error"
    assert result.char_count == 36000
    assert result.token_count == 9000


def test_get_char_count(tmp_path: Path):
    """get_char_count should return correct character count."""
    file_path = tmp_path / "hello.md"
    file_path.write_text("Hello World")  # 11 characters

    result = get_char_count(file_path)
    assert result == 11


def test_get_char_count_utf8(tmp_path: Path):
    """get_char_count should handle UTF-8 characters."""
    file_path = tmp_path / "utf8.md"
    file_path.write_text("Hello 世界", encoding="utf-8")  # 8 characters (not bytes)

    result = get_char_count(file_path)
    assert result == 8


def test_estimate_tokens_default_ratio():
    """estimate_tokens should convert chars to tokens using default ratio."""
    # 400 chars / 4 chars_per_token = 100 tokens
    result = estimate_tokens(400)
    assert result == 100


def test_estimate_tokens_custom_ratio():
    """estimate_tokens should accept custom chars_per_token ratio."""
    # 300 chars / 3 chars_per_token = 100 tokens
    result = estimate_tokens(300, chars_per_token=3)
    assert result == 100


def test_estimate_tokens_rounds_up():
    """estimate_tokens should round up partial tokens."""
    # 401 chars / 4 = 100.25, should round up to 101
    result = estimate_tokens(401)
    assert result == 101


def test_estimate_tokens_zero():
    """estimate_tokens should return 0 for 0 chars."""
    result = estimate_tokens(0)
    assert result == 0


def test_get_provider_for_claude_md():
    """get_provider_for_file should detect CLAUDE.md as anthropic."""
    result = get_provider_for_file(Path("CLAUDE.md"))
    assert result == "anthropic"


def test_get_provider_for_gemini_md():
    """get_provider_for_file should detect GEMINI.md as google."""
    result = get_provider_for_file(Path("GEMINI.md"))
    assert result == "google"


def test_get_provider_for_agents_md():
    """get_provider_for_file should detect AGENTS.md as default."""
    result = get_provider_for_file(Path("AGENTS.md"))
    assert result == "default"


def test_get_provider_for_copilot_instructions():
    """get_provider_for_file should detect copilot-instructions.md as default."""
    result = get_provider_for_file(Path(".github/copilot-instructions.md"))
    assert result == "default"


def test_get_provider_token_limit_anthropic():
    """get_provider_token_limit should return 8K tokens for anthropic."""
    result = get_provider_token_limit("anthropic")
    assert result == 8000  # 4% of 200K


def test_get_provider_token_limit_google():
    """get_provider_token_limit should return ~42K tokens for google."""
    result = get_provider_token_limit("google")
    assert result == 41943  # 4% of 1,048,576


def test_get_provider_token_limit_default():
    """get_provider_token_limit should return 8K tokens for default."""
    result = get_provider_token_limit("default")
    assert result == 8000  # 4% of 200K (conservative)


def test_get_provider_token_limit_unknown_key():
    """get_provider_token_limit should return default limit for unknown provider."""
    # Unknown provider key should fall back to default limit
    result = get_provider_token_limit("unknown_provider")
    assert result == 8000  # Same as default


def test_validate_file_exactly_at_info_threshold(tmp_path: Path):
    """validate_file should return ok when exactly at info threshold."""
    # Exactly 50% of 8000 = 4000 tokens = 16000 chars
    file_path = tmp_path / "at_info.md"
    file_path.write_text("a" * 16000)  # 4000 tokens, exactly 50%

    result = validate_file(file_path, chars_per_token=4, info_pct=50, warn_pct=75)

    # At exactly 50%, still ok (must exceed threshold to trigger info)
    assert result.status == "ok"


def test_validate_file_one_token_over_info_threshold(tmp_path: Path):
    """validate_file should return info when one token over info threshold."""
    # One token over 50% of 8000 = 4001 tokens = 16004 chars
    file_path = tmp_path / "over_info.md"
    file_path.write_text("a" * 16004)  # 4001 tokens, just over 50%

    result = validate_file(file_path, chars_per_token=4, info_pct=50, warn_pct=75)

    # One token over 50% triggers info
    assert result.status == "info"


def test_validate_file_just_under_info_threshold(tmp_path: Path):
    """validate_file should return ok when just under info threshold."""
    # Just under 50% of 8000 = 3999 tokens = 15996 chars
    file_path = tmp_path / "under_info.md"
    file_path.write_text("a" * 15996)  # 3999 tokens, just under 50%

    result = validate_file(file_path, chars_per_token=4, info_pct=50, warn_pct=75)

    assert result.status == "ok"


def test_validate_file_exactly_at_limit(tmp_path: Path):
    """validate_file should return warning when exactly at limit."""
    # Exactly 8000 tokens = 32000 chars (at limit, not over)
    file_path = tmp_path / "at_limit.md"
    file_path.write_text("a" * 32000)  # 8000 tokens, exactly at limit

    result = validate_file(file_path, chars_per_token=4, info_pct=50, warn_pct=75)

    # At exactly limit (100%), should be warning, not error
    assert result.status == "warning"


def test_validate_file_one_token_over_limit(tmp_path: Path):
    """validate_file should return error when one token over limit."""
    # 8001 tokens = 32004 chars (one token over)
    file_path = tmp_path / "over_limit.md"
    file_path.write_text("a" * 32004)  # 8001 tokens, one over limit

    result = validate_file(file_path, chars_per_token=4, info_pct=50, warn_pct=75)

    assert result.status == "error"


def test_validate_category_ok():
    """validate_category should return ok when total under info threshold."""
    # 5000 chars total, budget 24000, info at 50% = 12000
    result = validate_category(
        category_name="path_instructions",
        total_chars=5000,
        budget=24000,
        info_threshold_percent=50,
        warn_threshold_percent=75,
    )

    assert result.status == "ok"
    assert result.total_chars == 5000
    assert result.budget == 24000


def test_validate_category_info():
    """validate_category should return info when above info threshold."""
    # 14000 chars total, budget 24000, info at 50% = 12000
    result = validate_category(
        category_name="path_instructions",
        total_chars=14000,
        budget=24000,
        info_threshold_percent=50,
        warn_threshold_percent=75,
    )

    assert result.status == "info"


def test_validate_category_warning():
    """validate_category should return warning when above warn threshold."""
    # 20000 chars total, budget 24000, warn at 75% = 18000
    result = validate_category(
        category_name="path_instructions",
        total_chars=20000,
        budget=24000,
        info_threshold_percent=50,
        warn_threshold_percent=75,
    )

    assert result.status == "warning"


def test_validate_category_error():
    """validate_category should return error when over budget."""
    # 25000 chars total, budget 24000 = over budget
    result = validate_category(
        category_name="path_instructions",
        total_chars=25000,
        budget=24000,
        info_threshold_percent=50,
        warn_threshold_percent=75,
    )

    assert result.status == "error"


def test_detect_outliers_no_outliers():
    """detect_outliers should return empty lists when no outliers exist."""
    # All files similar size, no outliers (IQR method needs at least 4 files)
    file_sizes = [1000, 1100, 1050, 950, 1000, 1025]
    lower, upper = detect_outliers(file_sizes, iqr_multiplier=1.5)
    assert lower == []
    assert upper == []


def test_detect_outliers_with_upper_outlier():
    """detect_outliers should identify file significantly larger than peers."""
    # Need enough clustered data so outlier is clearly outside upper fence
    # With [100, 101, 102, 103, 104, 105, 106, 5000]:
    # Q1=101.25, Q3=105.75, IQR=4.5, Upper fence = 105.75 + 6.75 = 112.5
    # 5000 > 112.5 = True (outlier at index 7)
    file_sizes = [100, 101, 102, 103, 104, 105, 106, 5000]
    lower, upper = detect_outliers(file_sizes, iqr_multiplier=1.5)
    assert 7 in upper
    assert lower == []


def test_detect_outliers_with_lower_outlier():
    """detect_outliers should identify file significantly smaller than peers."""
    # File at index 0 is way smaller than others (outside lower fence)
    # With [10, 1000, 1100, 1200, 1300]: Q1=505, Q3=1150, IQR=645
    # Lower fence = 505 - 1.5*645 = -462.5, so 10 is not outlier
    # Need tighter spread: [10, 900, 950, 1000, 1050]
    # Q1=455, Q3=975, IQR=520, Lower fence = 455 - 780 = -325 (10 not outlier)
    # Try: [5, 1000, 1010, 1020, 1030]: Q1=505, Q3=1015, IQR=510
    # Lower fence = 505 - 765 = -260 (5 not outlier)
    # Need extreme case: all clustered except one tiny
    file_sizes = [1, 1000, 1000, 1000, 1000]
    lower, _ = detect_outliers(file_sizes, iqr_multiplier=1.5)
    # Q1=500.5, Q3=1000, IQR=499.5, Lower fence = 500.5 - 749.25 = -248.75
    # 1 > -248.75 so NOT a lower outlier with this data
    # IQR method needs more spread. Use multiplier 0.5 for stricter test
    lower, _ = detect_outliers(file_sizes, iqr_multiplier=0.1)
    # Lower fence = 500.5 - 49.95 = 450.55, so 1 < 450.55 is outlier
    assert 0 in lower


def test_detect_outliers_insufficient_files():
    """detect_outliers should return empty for fewer than 4 files."""
    # Need at least 4 files for quartile calculation
    file_sizes = [1000, 2000, 3000]
    lower, upper = detect_outliers(file_sizes, iqr_multiplier=1.5)
    assert lower == []
    assert upper == []


def test_detect_outliers_empty_list():
    """detect_outliers should return empty for empty input."""
    file_sizes = []
    lower, upper = detect_outliers(file_sizes, iqr_multiplier=1.5)
    assert lower == []
    assert upper == []


def test_detect_outliers_all_same():
    """detect_outliers should return empty when all files are same size."""
    # Zero IQR, no outliers possible
    file_sizes = [1000, 1000, 1000, 1000]
    lower, upper = detect_outliers(file_sizes, iqr_multiplier=1.5)
    assert lower == []
    assert upper == []


# --- Baseline Comparison Tests ---


def test_compute_baseline_stats_returns_stats():
    """compute_baseline_stats should return BaselineStats with computed values."""
    # 8 tightly clustered values
    file_sizes = [100, 101, 102, 103, 104, 105, 106, 107]
    stats = compute_baseline_stats(file_sizes, iqr_multiplier=1.5)

    assert stats is not None
    assert stats.file_count == 8
    assert stats.q1 < stats.q3
    assert stats.iqr > 0
    assert stats.lower_fence < stats.q1
    assert stats.upper_fence > stats.q3


def test_compute_baseline_stats_insufficient_data():
    """compute_baseline_stats should return None for fewer than 4 files."""
    file_sizes = [100, 200, 300]
    stats = compute_baseline_stats(file_sizes, iqr_multiplier=1.5)

    assert stats is None


def test_compute_baseline_stats_zero_iqr():
    """compute_baseline_stats should return None when IQR is zero."""
    file_sizes = [100, 100, 100, 100]
    stats = compute_baseline_stats(file_sizes, iqr_multiplier=1.5)

    assert stats is None


def test_compute_baseline_stats_detects_outlier():
    """compute_baseline_stats fences should correctly identify outliers."""
    # Tightly clustered data
    file_sizes = [100, 101, 102, 103, 104, 105, 106, 107]
    stats = compute_baseline_stats(file_sizes, iqr_multiplier=1.5)

    assert stats is not None
    # A value of 5000 should be above upper fence
    assert stats.upper_fence < 5000
    # A value of 1 should be below lower fence (with this tight clustering)
    assert stats.lower_fence > 1


def test_get_char_count_returns_zero_on_os_error():
    """get_char_count should return 0 when file cannot be read."""
    result = get_char_count(Path("/nonexistent/path/missing.md"))
    assert result == 0


def test_get_char_count_returns_zero_on_unicode_error(tmp_path: Path):
    """get_char_count should return 0 for files with invalid UTF-8."""
    bad_file = tmp_path / "bad.md"
    bad_file.write_bytes(b"\xff\xfe invalid utf-8 \x80\x81")
    result = get_char_count(bad_file)
    assert result == 0
