"""Git utility functions for context validation."""

import subprocess
from pathlib import Path


def get_changed_files(ref_branch: str, repo_root: Path) -> list[Path]:
    """Get list of files changed between ref_branch and HEAD.

    Args:
        ref_branch: Reference branch to compare against (e.g., 'origin/main').
        repo_root: Root directory of the repository.

    Returns:
        List of Paths for files that are new or modified in HEAD vs ref_branch.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{ref_branch}...HEAD"],
            capture_output=True,
            text=True,
            cwd=repo_root,
            check=True,
        )
        changed = []
        for line in result.stdout.strip().split("\n"):
            if line:
                changed.append(repo_root / line)
        return changed
    except subprocess.CalledProcessError:
        return []


def get_file_content_from_branch(file_path: str, branch: str, repo_root: Path) -> str | None:
    """Read file content from a specific git branch without checkout.

    Args:
        file_path: Path relative to repo root (e.g., '.github/instructions/foo.md').
        branch: Git branch or ref to read from (e.g., 'origin/main').
        repo_root: Root directory of the repository.

    Returns:
        File content as string, or None if file doesn't exist on that branch.
    """
    try:
        result = subprocess.run(
            ["git", "show", f"{branch}:{file_path}"],
            capture_output=True,
            text=True,
            cwd=repo_root,
            check=True,
        )
        return result.stdout
    except subprocess.CalledProcessError:
        return None


def get_baseline_file_sizes(
    patterns: list[str],
    ref_branch: str,
    repo_root: Path,
) -> dict[str, list[tuple[str, int]]]:
    """Get file sizes from reference branch for baseline calculation.

    Args:
        patterns: List of glob patterns to match (e.g., '.github/instructions/*.md').
        ref_branch: Reference branch to read files from.
        repo_root: Root directory of the repository.

    Returns:
        Dict mapping pattern to list of (file_path, char_count) tuples.
    """
    # Get list of files on the reference branch using git ls-tree
    try:
        result = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", ref_branch],
            capture_output=True,
            text=True,
            cwd=repo_root,
            check=True,
        )
        all_files = result.stdout.strip().split("\n")
    except subprocess.CalledProcessError:
        return {}

    baseline_files: dict[str, list[tuple[str, int]]] = {}

    for pattern in patterns:
        baseline_files[pattern] = []
        for file_path in all_files:
            # Match pattern using Path matching
            if Path(file_path).match(pattern.lstrip("*").lstrip("/")):
                content = get_file_content_from_branch(file_path, ref_branch, repo_root)
                if content is not None:
                    baseline_files[pattern].append((file_path, len(content)))

    return baseline_files
