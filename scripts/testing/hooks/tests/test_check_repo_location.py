from __future__ import annotations

from pathlib import Path
from typing import Any

import scripts.testing.hooks.check_repo_location as mod


def _fake_run(results: dict[tuple[str, ...], tuple[int, str, str]]):
    def runner(args):
        return results.get(tuple(args), (1, "", ""))

    return runner


def test_skip_env(monkeypatch: Any) -> None:
    monkeypatch.setenv("SKIP_REPO_LOCATION_CHECK", "1")
    assert mod.main() == 0
    monkeypatch.delenv("SKIP_REPO_LOCATION_CHECK", raising=False)


def test_valid_repo(monkeypatch: Any, tmp_path: Path) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    results: dict[tuple[str, ...], tuple[int, str, str]] = {
        ("rev-parse", "--git-dir"): (0, str(git_dir), ""),
        ("rev-parse", "--show-toplevel"): (0, str(tmp_path), ""),
    }
    monkeypatch.setattr(mod, "_run_git", _fake_run(results))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert mod.main() == 0


def test_worktree_blocks(monkeypatch: Any, tmp_path: Path) -> None:
    wt_git_dir = tmp_path / ".git" / "worktrees" / "wt"
    wt_git_dir.mkdir(parents=True)
    results: dict[tuple[str, ...], tuple[int, str, str]] = {
        ("rev-parse", "--git-dir"): (0, str(wt_git_dir), ""),
        ("rev-parse", "--show-toplevel"): (0, str(tmp_path), ""),
    }
    monkeypatch.setattr(mod, "_run_git", _fake_run(results))
    assert mod.main() == 1


def test_git_dir_failure(monkeypatch: Any) -> None:
    """_is_worktree returns False when git rev-parse --git-dir fails."""
    results: dict[tuple[str, ...], tuple[int, str, str]] = {
        ("rev-parse", "--git-dir"): (1, "", "not a git repo"),
    }
    monkeypatch.setattr(mod, "_run_git", _fake_run(results))
    is_wt, _ = mod._is_worktree()
    assert is_wt is False


def test_git_dir_is_file(monkeypatch: Any, tmp_path: Path) -> None:
    """_is_worktree detects worktree when .git is a file."""
    git_file = tmp_path / ".git_file"
    git_file.write_text("gitdir: /path/to/worktree")
    results: dict[tuple[str, ...], tuple[int, str, str]] = {
        ("rev-parse", "--git-dir"): (0, str(git_file), ""),
    }
    monkeypatch.setattr(mod, "_run_git", _fake_run(results))
    is_wt, wt_path = mod._is_worktree()
    assert is_wt is True
    assert wt_path == str(git_file.resolve())


def test_worktrees_not_adjacent_to_git_dir(monkeypatch: Any, tmp_path: Path) -> None:
    """_is_worktree returns False when '.git' and 'worktrees' not adjacent."""
    # Path like: /some/worktrees/path/.git/objects (not a worktree)
    git_dir = tmp_path / "worktrees" / "repo" / ".git"
    git_dir.mkdir(parents=True)
    results: dict[tuple[str, ...], tuple[int, str, str]] = {
        ("rev-parse", "--git-dir"): (0, str(git_dir), ""),
    }
    monkeypatch.setattr(mod, "_run_git", _fake_run(results))
    is_wt, _ = mod._is_worktree()
    assert is_wt is False


def test_show_toplevel_failure(monkeypatch: Any) -> None:
    """_get_repo_root returns None when git rev-parse --show-toplevel fails."""
    results: dict[tuple[str, ...], tuple[int, str, str]] = {
        ("rev-parse", "--show-toplevel"): (1, "", "not a git repo"),
    }
    monkeypatch.setattr(mod, "_run_git", _fake_run(results))
    repo_root = mod._get_repo_root()
    assert repo_root is None


def test_check_repo_location_no_repo_root(monkeypatch: Any) -> None:
    """check_repo_location returns error when _get_repo_root fails."""
    results: dict[tuple[str, ...], tuple[int, str, str]] = {
        ("rev-parse", "--git-dir"): (0, ".git", ""),
        ("rev-parse", "--show-toplevel"): (1, "", "not a git repo"),
    }
    monkeypatch.setattr(mod, "_run_git", _fake_run(results))
    is_valid, message = mod.check_repo_location()
    assert is_valid is False
    assert "Unable to determine repository root" in message


def test_valid_repo_path(monkeypatch: Any, tmp_path: Path) -> None:
    """check_repo_location accepts a standard repo path."""
    repo_path = tmp_path / "repos" / "my-repo"
    repo_path.mkdir(parents=True)
    git_dir = repo_path / ".git"
    git_dir.mkdir()
    results: dict[tuple[str, ...], tuple[int, str, str]] = {
        ("rev-parse", "--git-dir"): (0, str(git_dir), ""),
        ("rev-parse", "--show-toplevel"): (0, str(repo_path), ""),
    }
    monkeypatch.setattr(mod, "_run_git", _fake_run(results))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    is_valid, _ = mod.check_repo_location()
    assert is_valid is True


def test_repo_outside_home_blocked(monkeypatch: Any, tmp_path: Path) -> None:
    """check_repo_location blocks repos outside the user's home directory."""
    repo_path = tmp_path / "repos" / "my-repo"
    repo_path.mkdir(parents=True)
    git_dir = repo_path / ".git"
    git_dir.mkdir()
    results: dict[tuple[str, ...], tuple[int, str, str]] = {
        ("rev-parse", "--git-dir"): (0, str(git_dir), ""),
        ("rev-parse", "--show-toplevel"): (0, str(repo_path), ""),
    }
    monkeypatch.setattr(mod, "_run_git", _fake_run(results))
    # Point home to a different directory so repo_path is outside it
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "other-home"))
    is_valid, message = mod.check_repo_location()
    assert is_valid is False
    assert "outside your home directory" in message


def test_repo_under_home_allowed(monkeypatch: Any, tmp_path: Path) -> None:
    """check_repo_location accepts repos under the user's home directory."""
    home = tmp_path / "home" / "user"
    repo_path = home / "repos" / "my-repo"
    repo_path.mkdir(parents=True)
    git_dir = repo_path / ".git"
    git_dir.mkdir()
    results: dict[tuple[str, ...], tuple[int, str, str]] = {
        ("rev-parse", "--git-dir"): (0, str(git_dir), ""),
        ("rev-parse", "--show-toplevel"): (0, str(repo_path), ""),
    }
    monkeypatch.setattr(mod, "_run_git", _fake_run(results))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    is_valid, _ = mod.check_repo_location()
    assert is_valid is True


def test_run_git_delegates_to_subprocess(monkeypatch: Any) -> None:
    """_run_git() calls subprocess.run with correct args and returns results."""
    import subprocess
    from unittest.mock import MagicMock

    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = "  output text  "
    fake_result.stderr = "  warning  "

    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: fake_result)
    returncode, stdout, stderr = mod._run_git(["status", "--short"])
    assert returncode == 0
    assert stdout == "output text"
    assert stderr == "warning"
