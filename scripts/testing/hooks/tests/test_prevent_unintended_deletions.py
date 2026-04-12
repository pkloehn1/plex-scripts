from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from scripts.testing.hooks import prevent_unintended_deletions as mod

# TODO(#23): Enforce repo-wide coverage >= 80% in CI. # NOSONAR

_DIFF_DELETIONS_CMD = ["git", "diff", "--cached", "--name-status", "--diff-filter=D"]
_DIFF_STAGED_PREFIX = ["git", "diff", "--cached", "--name-only"]
_LS_DELETED_PREFIX = ["git", "ls-files", "--deleted"]


@dataclass(frozen=True)
class _FakeCompletedProcess:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


def _make_fake_run(
    *,
    deletions: _FakeCompletedProcess | None = None,
    staged: _FakeCompletedProcess | None = None,
    ls_deleted: _FakeCompletedProcess | None = None,
) -> Callable[[list[str]], _FakeCompletedProcess]:
    """Build a fake subprocess dispatcher for the three git commands used by the hook."""

    def handler(cmd: list[str]) -> _FakeCompletedProcess:
        if deletions is not None and cmd == _DIFF_DELETIONS_CMD:
            return deletions
        if staged is not None and cmd[:4] == _DIFF_STAGED_PREFIX:
            return staged
        if ls_deleted is not None and cmd[:3] == _LS_DELETED_PREFIX:
            return ls_deleted
        return _FakeCompletedProcess()

    return handler


def _with_fake_run(
    monkeypatch,
    handler: Callable[[list[str]], _FakeCompletedProcess],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(mod, "_resolve_git_dir", lambda: tmp_path / ".git")
    monkeypatch.setattr(mod, "_configure_logging", lambda _git_dir: None)
    monkeypatch.setattr(mod, "run", handler)


def test_parse_nonempty_lines_strips_and_filters() -> None:
    out = "\n D\tfoo.txt \n\nA\tbar.txt\n  \n"
    assert mod.parse_nonempty_lines(out) == ["D\tfoo.txt", "A\tbar.txt"]


def test_protected_paths_contains_repo_critical_files() -> None:
    assert "docker-compose.yml" in mod.PROTECTED_PATHS
    assert ".pre-commit-config.yaml" in mod.PROTECTED_PATHS
    assert ".github/workflows/super-linter.yml" in mod.PROTECTED_PATHS


def test_main_fails_on_staged_deletions(monkeypatch, tmp_path: Path, capsys) -> None:
    handler = _make_fake_run(deletions=_FakeCompletedProcess(stdout="D\tfoo.txt\n"))
    _with_fake_run(monkeypatch, handler, tmp_path)
    exit_code = mod.main()
    assert exit_code == 1

    err = capsys.readouterr().err
    assert "Staged deletions detected" in err
    assert "D\tfoo.txt" in err
    assert "--no-verify" in err


def test_main_fails_when_staged_files_missing(monkeypatch, tmp_path: Path, capsys) -> None:
    handler = _make_fake_run(
        deletions=_FakeCompletedProcess(stdout=""),
        staged=_FakeCompletedProcess(stdout="missing.txt\n"),
    )
    _with_fake_run(monkeypatch, handler, tmp_path)
    monkeypatch.setattr(mod.os.path, "exists", lambda _path: False)

    exit_code = mod.main()
    assert exit_code == 1

    err = capsys.readouterr().err
    assert "Staged files missing" in err
    assert "missing.txt" in err


def test_main_fails_when_protected_files_deleted(monkeypatch, tmp_path: Path, capsys) -> None:
    handler = _make_fake_run(
        deletions=_FakeCompletedProcess(stdout=""),
        staged=_FakeCompletedProcess(stdout="ok.txt\n"),
        ls_deleted=_FakeCompletedProcess(stdout=".pre-commit-config.yaml\n"),
    )
    _with_fake_run(monkeypatch, handler, tmp_path)
    monkeypatch.setattr(mod.os.path, "exists", lambda _path: True)

    exit_code = mod.main()
    assert exit_code == 1

    err = capsys.readouterr().err
    assert "Protected files deleted" in err
    assert ".pre-commit-config.yaml" in err
    assert "git restore" in err


def test_main_succeeds_when_all_checks_pass(monkeypatch, tmp_path: Path) -> None:
    handler = _make_fake_run(
        deletions=_FakeCompletedProcess(stdout=""),
        staged=_FakeCompletedProcess(stdout="ok.txt\n"),
        ls_deleted=_FakeCompletedProcess(stdout=""),
    )
    _with_fake_run(monkeypatch, handler, tmp_path)
    monkeypatch.setattr(mod.os.path, "exists", lambda _path: True)

    assert mod.main() == 0


def test_main_fails_when_git_diff_staged_deletions_command_errors(monkeypatch, tmp_path: Path, capsys) -> None:
    handler = _make_fake_run(deletions=_FakeCompletedProcess(returncode=1, stderr="boom\n"))
    _with_fake_run(monkeypatch, handler, tmp_path)
    exit_code = mod.main()
    assert exit_code == 1

    err = capsys.readouterr().err
    assert "boom" in err


def test_main_fails_when_git_diff_staged_files_command_errors(monkeypatch, tmp_path: Path, capsys) -> None:
    handler = _make_fake_run(
        deletions=_FakeCompletedProcess(stdout=""),
        staged=_FakeCompletedProcess(returncode=1, stderr="nope\n"),
    )
    _with_fake_run(monkeypatch, handler, tmp_path)
    exit_code = mod.main()
    assert exit_code == 1

    err = capsys.readouterr().err
    assert "nope" in err


def test_main_fails_when_git_ls_files_deleted_command_errors(monkeypatch, tmp_path: Path, capsys) -> None:
    handler = _make_fake_run(
        deletions=_FakeCompletedProcess(stdout=""),
        staged=_FakeCompletedProcess(stdout="ok.txt\n"),
        ls_deleted=_FakeCompletedProcess(returncode=1, stderr="bad\n"),
    )
    _with_fake_run(monkeypatch, handler, tmp_path)
    monkeypatch.setattr(mod.os.path, "exists", lambda _path: True)

    exit_code = mod.main()
    assert exit_code == 1

    err = capsys.readouterr().err
    assert "bad" in err


def test_run_delegates_to_subprocess() -> None:
    """run() delegates to subprocess.run()."""
    result = mod.run(["git", "--version"])
    assert result.returncode == 0
    assert "git version" in result.stdout.lower()


def test_resolve_git_dir_git_rev_parse_fails(monkeypatch, capsys) -> None:
    """_resolve_git_dir() returns None when git rev-parse --git-dir fails."""

    def fake_run(cmd: list[str]) -> _FakeCompletedProcess:
        if cmd == ["git", "rev-parse", "--git-dir"]:
            return _FakeCompletedProcess(returncode=1, stderr="not a git repo")
        return _FakeCompletedProcess()

    monkeypatch.setattr(mod, "run", fake_run)
    assert mod._resolve_git_dir() is None
    err = capsys.readouterr().err
    assert "Not in a git repository" in err


def test_resolve_git_dir_empty_stdout(monkeypatch, capsys) -> None:
    """_resolve_git_dir() returns None when git dir is empty."""

    def fake_run(cmd: list[str]) -> _FakeCompletedProcess:
        if cmd == ["git", "rev-parse", "--git-dir"]:
            return _FakeCompletedProcess(stdout="  \n")
        return _FakeCompletedProcess()

    monkeypatch.setattr(mod, "run", fake_run)
    assert mod._resolve_git_dir() is None
    err = capsys.readouterr().err
    assert "Unable to determine git directory" in err


def test_resolve_git_dir_absolute_path(monkeypatch, tmp_path: Path) -> None:
    """_resolve_git_dir() returns absolute path when git-dir is absolute."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    def fake_run(cmd: list[str]) -> _FakeCompletedProcess:
        if cmd == ["git", "rev-parse", "--git-dir"]:
            return _FakeCompletedProcess(stdout=str(git_dir))
        return _FakeCompletedProcess()

    monkeypatch.setattr(mod, "run", fake_run)
    result = mod._resolve_git_dir()
    assert result == git_dir


def test_resolve_git_dir_relative_path_show_toplevel_fails(monkeypatch, tmp_path: Path) -> None:
    """_resolve_git_dir() uses cwd when relative and show-toplevel fails."""

    def fake_run(cmd: list[str]) -> _FakeCompletedProcess:
        if cmd == ["git", "rev-parse", "--git-dir"]:
            return _FakeCompletedProcess(stdout=".git")
        if cmd == ["git", "rev-parse", "--show-toplevel"]:
            return _FakeCompletedProcess(returncode=1)
        return _FakeCompletedProcess()

    monkeypatch.setattr(mod, "run", fake_run)
    result = mod._resolve_git_dir()
    assert result is not None
    assert result.name == ".git"


def test_resolve_git_dir_relative_path_empty_toplevel(monkeypatch, tmp_path: Path) -> None:
    """_resolve_git_dir() uses cwd when relative and toplevel is empty."""

    def fake_run(cmd: list[str]) -> _FakeCompletedProcess:
        if cmd == ["git", "rev-parse", "--git-dir"]:
            return _FakeCompletedProcess(stdout=".git")
        if cmd == ["git", "rev-parse", "--show-toplevel"]:
            return _FakeCompletedProcess(stdout="  \n")
        return _FakeCompletedProcess()

    monkeypatch.setattr(mod, "run", fake_run)
    result = mod._resolve_git_dir()
    assert result is not None
    assert result.name == ".git"


def test_resolve_git_dir_relative_path_with_toplevel(monkeypatch, tmp_path: Path) -> None:
    """_resolve_git_dir() resolves relative path against toplevel."""

    def fake_run(cmd: list[str]) -> _FakeCompletedProcess:
        if cmd == ["git", "rev-parse", "--git-dir"]:
            return _FakeCompletedProcess(stdout=".git")
        if cmd == ["git", "rev-parse", "--show-toplevel"]:
            return _FakeCompletedProcess(stdout=str(tmp_path))
        return _FakeCompletedProcess()

    monkeypatch.setattr(mod, "run", fake_run)
    result = mod._resolve_git_dir()
    assert result == (tmp_path / ".git").resolve()


def test_configure_logging_creates_log_file(tmp_path: Path) -> None:
    """_configure_logging() creates log file in git hooks directory."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    mod._configure_logging(git_dir)
    log_file = git_dir / "hooks" / "deletion-prevention.log"
    assert log_file.parent.exists()


def test_main_fails_when_resolve_git_dir_returns_none(monkeypatch, capsys) -> None:
    """main() returns 1 when _resolve_git_dir() fails."""
    monkeypatch.setattr(mod, "_resolve_git_dir", lambda: None)
    assert mod.main() == 1
