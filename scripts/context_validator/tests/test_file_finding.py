"""Tests for file finding functionality.

Tests use discovery patterns to avoid hardcoding specific filenames.
"""

import tempfile
from pathlib import Path

from scripts.common.paths import repo_root


def test_find_files_exact_path_with_temp_file():
    """find_files should find a single file by exact path."""
    from scripts.context_validator.utils import find_files

    # Create temp file in repo root to test exact path matching
    root = repo_root()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", dir=root, delete=False) as f:
        f.write("test content")
        temp_name = Path(f.name).name

    try:
        result = find_files(root, temp_name)
        assert len(result) == 1
        assert result[0].name == temp_name
    finally:
        (root / temp_name).unlink()


def test_find_files_discovers_dotgithub_files():
    """find_files should discover files in .github directory."""
    from scripts.context_validator.utils import find_files

    root = repo_root()

    # Test that .github directory files can be found
    github_dir = root / ".github"
    if github_dir.exists():
        # Find any .md file in .github
        result = find_files(root, ".github/*.md")
        # Should find at least one file if .github exists
        assert len(result) > 0


def test_find_files_glob_discovers_instruction_files():
    """find_files should discover instruction files matching pattern."""
    from scripts.context_validator.utils import find_files

    root = repo_root()
    result = find_files(root, ".github/instructions/*.instructions.md")

    # Verify pattern matching works (files end with .instructions.md)
    for f in result:
        assert f.name.endswith(".instructions.md")
        assert f.suffix == ".md"


def test_find_files_glob_discovers_prompt_files():
    """find_files should discover prompt files matching pattern."""
    from scripts.context_validator.utils import find_files

    root = repo_root()
    result = find_files(root, ".github/prompts/*.prompt.md")

    # Verify pattern matching works (files end with .prompt.md)
    for f in result:
        assert f.name.endswith(".prompt.md")
        assert f.suffix == ".md"


def test_find_files_nonexistent_returns_empty():
    """find_files should return empty list for nonexistent files."""
    from scripts.context_validator.utils import find_files

    root = repo_root()
    result = find_files(root, "NONEXISTENT_FILE_12345.md")

    assert result == []


def test_find_files_nonexistent_glob_returns_empty():
    """find_files should return empty list for unmatched glob pattern."""
    from scripts.context_validator.utils import find_files

    root = repo_root()
    result = find_files(root, ".github/nonexistent_dir_12345/*.md")

    assert result == []
