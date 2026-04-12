#!/usr/bin/env python3
"""Block commits that include staged deletions (D), missing staged files, or protected file deletions.

Rationale:
- Prevents accidental file removals caused by file-modifying hooks or editor/EOL churn.
- Detects index corruption from pre-commit stash/restore mechanism.
- Protects critical repo files from accidental deletion.
- Runs both before and after other hooks to catch deletions at any stage.

Behavior:
- Check 1: Detect staged deletions (D status)
- Check 2: Verify all staged files exist in working directory
- Check 3: Verify protected files (critical repo files) are not deleted from working tree
- If any check fails, print diagnostics and exit non-zero.
- Does not modify the index; purely a guardrail.

Protected files:
- docker-compose.yml
- .pre-commit-config.yaml
- .github/workflows/super-linter.yml

Override:
- By default, staged deletions are forbidden.

"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

PROTECTED_PATHS = {
    "docker-compose.yml",
    ".pre-commit-config.yaml",
    ".github/workflows/super-linter.yml",
}


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def parse_nonempty_lines(output: str) -> list[str]:
    return [line.strip() for line in output.splitlines() if line.strip()]


def _resolve_git_dir() -> Path | None:
    proc = run(["git", "rev-parse", "--git-dir"])
    if proc.returncode != 0:
        sys.stderr.write("ERROR: Not in a git repository. This hook must run from a repository checkout.\n")
        if proc.stderr:
            sys.stderr.write(proc.stderr)
        return None

    git_dir_raw = proc.stdout.strip()
    if not git_dir_raw:
        sys.stderr.write("ERROR: Unable to determine git directory.\n")
        return None

    git_dir = Path(git_dir_raw)
    if git_dir.is_absolute():
        return git_dir

    # Resolve relative git dir against repo root.
    cp_root = run(["git", "rev-parse", "--show-toplevel"])
    if cp_root.returncode != 0:
        return (Path.cwd() / git_dir).resolve()

    repo_root_raw = cp_root.stdout.strip()
    if not repo_root_raw:
        return (Path.cwd() / git_dir).resolve()

    return (Path(repo_root_raw) / git_dir).resolve()


def _configure_logging(git_dir: Path) -> None:
    log_file = git_dir / "hooks" / "deletion-prevention.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(log_file),
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _check_staged_deletions() -> bool:
    proc = run(["git", "diff", "--cached", "--name-status", "--diff-filter=D"])
    if proc.returncode != 0:
        logging.error("git diff failed: %s", proc.stderr)
        sys.stderr.write(proc.stderr)
        return False

    deleted = parse_nonempty_lines(proc.stdout)
    logging.debug("Check 1: Staged deletions found: %d", len(deleted))
    for line in deleted:
        logging.debug("  %s", line)

    if not deleted:
        return True

    sys.stderr.write("\nERROR: Staged deletions detected. Commit aborted.\n")
    sys.stderr.write("Repository policy forbids unintended deletions.\n\n")
    sys.stderr.write("Staged deletions (name-status):\n")
    for line in deleted:
        sys.stderr.write(f"  {line}\n")
    sys.stderr.write("\nIf this deletion is intentional:\n")
    sys.stderr.write("  1. Stage exactly ONE deletion\n")
    sys.stderr.write("  2. Commit it with an explicit message\n")
    sys.stderr.write("  3. Bypass local hooks with --no-verify\n\n")
    sys.stderr.write("Example:\n")
    sys.stderr.write("  git add <deleted-file>\n")
    sys.stderr.write('  git commit --no-verify -m "chore: remove <deleted-file> (intentional)"\n')
    logging.warning("Commit aborted: staged deletions detected")
    return False


def _check_staged_files_exist() -> bool:
    cp_staged_paths = run(["git", "diff", "--cached", "--name-only"])
    if cp_staged_paths.returncode != 0:
        logging.error("git diff --cached --name-only failed: %s", cp_staged_paths.stderr)
        sys.stderr.write(cp_staged_paths.stderr)
        return False

    missing_files: list[str] = []
    for filepath in parse_nonempty_lines(cp_staged_paths.stdout):
        if not os.path.exists(filepath):
            missing_files.append(filepath)
            logging.warning("Check 2: Staged file missing from working directory: %s", filepath)

    if not missing_files:
        return True

    sys.stderr.write("\nERROR: Staged files missing from working directory. Commit aborted.\n")
    sys.stderr.write("This indicates git index corruption (possibly from pre-commit stash/restore).\n\n")
    sys.stderr.write("Missing files:\n")
    for filepath in missing_files:
        sys.stderr.write(f"  {filepath}\n")
    sys.stderr.write("\nRecommended recovery:\n")
    sys.stderr.write("  1. Run: git status --porcelain\n")
    sys.stderr.write("  2. Verify file exists in working directory\n")
    sys.stderr.write("  3. Re-stage file: git add <file>\n")
    sys.stderr.write("  4. Retry commit\n")
    logging.error("Commit aborted: staged files missing from working directory (index corruption)")
    return False


def _check_protected_files_not_deleted() -> bool:
    cp_deleted_working_tree = run(["git", "ls-files", "--deleted"])
    if cp_deleted_working_tree.returncode != 0:
        logging.error("git ls-files --deleted failed: %s", cp_deleted_working_tree.stderr)
        sys.stderr.write(cp_deleted_working_tree.stderr)
        return False

    deleted_in_working_tree = {line.strip() for line in cp_deleted_working_tree.stdout.splitlines() if line.strip()}
    protected_deleted_in_working_tree = sorted(deleted_in_working_tree & PROTECTED_PATHS)
    logging.debug(
        "Check 3: Protected files deleted from working tree: %d",
        len(protected_deleted_in_working_tree),
    )
    for path_str in protected_deleted_in_working_tree:
        logging.debug("  %s", path_str)

    if not protected_deleted_in_working_tree:
        return True

    sys.stderr.write("\nERROR: Protected files deleted from working directory. Commit aborted.\n")
    sys.stderr.write("Repository policy forbids deletion of critical files without explicit approval.\n\n")
    sys.stderr.write("Deleted protected files:\n")
    for path_str in protected_deleted_in_working_tree:
        sys.stderr.write(f"  {path_str}\n")
    sys.stderr.write("\nIf this deletion is intentional:\n")
    sys.stderr.write("  1. Restore file: git restore <file>\n")
    sys.stderr.write("  2. Create explicit deletion commit with justification\n")
    sys.stderr.write("  3. Get approval before merging\n")
    logging.error("Commit aborted: protected files deleted from working tree")
    return False


def main() -> int:
    git_dir = _resolve_git_dir()
    if git_dir is None:
        return 1

    _configure_logging(git_dir)
    logging.debug("=" * 60)
    logging.debug("Running deletion prevention check (3 checks)")

    if not _check_staged_deletions():
        return 1
    if not _check_staged_files_exist():
        return 1
    if not _check_protected_files_not_deleted():
        return 1

    logging.debug("All checks passed: no deletions, all staged files exist, all protected files present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
