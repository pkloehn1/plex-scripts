"""Integration tests for main function.

Tests validate script behavior without hardcoding specific filenames.
"""

import subprocess
import sys

from scripts.common.paths import repo_root
from scripts.validate_context_limits import main as validate_main


def run_validation_script() -> subprocess.CompletedProcess:
    """Run the validation script and return the result."""
    return subprocess.run(
        [sys.executable, "-m", "scripts.validate_context_limits"],
        capture_output=True,
        text=True,
        cwd=repo_root(),
        check=False,  # We check returncode explicitly in tests
    )


def test_main_produces_output():
    """Main should produce validation output."""
    result = run_validation_script()

    # Script should produce some output
    assert len(result.stdout) > 0
    assert "Validating" in result.stdout or "Summary" in result.stdout


def test_main_validates_discovered_files():
    """Main should validate files it discovers based on config patterns."""
    result = run_validation_script()

    # Script should report status icons or token counts
    output = result.stdout
    # Check for common output elements in new format
    assert "tokens" in output
    assert "[" in output and "]" in output  # Provider name brackets


def test_main_reports_summary():
    """Main should report a summary of validation results."""
    result = run_validation_script()

    assert "Total:" in result.stdout
    assert "tokens across" in result.stdout


def test_main_returns_zero_when_all_pass():
    """Main should return 0 when all files are within limits."""
    result = run_validation_script()

    # Only assert return code 0 if no errors reported
    if "FAILED:" not in result.stdout:
        assert result.returncode == 0


def test_main_uses_config_file():
    """Main should use the centralized config file."""
    # Verify config file exists
    config_path = repo_root() / "scripts" / "copilot-context-health.conf"
    assert config_path.exists(), "Config file should exist"

    # Run script - it will fail if config is missing
    result = run_validation_script()
    assert result.returncode in [0, 1]  # Should not crash


def test_main_reports_provider_limits():
    """Main should report provider-specific token limits."""
    result = run_validation_script()

    # Script should report provider limits in header
    assert "Provider limits:" in result.stdout
    # Should show per-file token validation with provider info
    assert "tokens" in result.stdout


def test_wrapper_module_exposes_main():
    """The validate_context_limits wrapper module re-exports main."""
    assert callable(validate_main)
